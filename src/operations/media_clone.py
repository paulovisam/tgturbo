import os, time, asyncio
from .base import BaseOperation
from pyrogram.client import Client
from pyrogram.types import ChatPrivileges
from pyrogram.errors import (
    MessageIdInvalid,
    MessageEmpty,
    PeerIdInvalid,
    MessageNotModified,
    FileReferenceExpired,
)
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path, get_chat_history
from src.ffmpeg_utils import (
    needs_reencode,
    build_ffmpeg_cmd,
    get_codec,
    extract_video_thumbnail_jpeg,
    get_video_dimensions,
    get_video_duration,
    is_video_file,
)


class MediaClone(BaseOperation):
    """Operação: Mover mensagens de um grupo para outro"""

    def __init__(
        self,
        client: Client,
        config,
        origin_chat_id: int,
        destination_chat_id: int,
        progress_tracker: ProgressTracker,
        add_suffix: str,
        remove_suffix: str,
    ):
        super().__init__(client, progress_tracker)
        self.client = client
        self.config = config['clone']
        self.origin_chat_id = origin_chat_id
        self.destination_chat_id = destination_chat_id
        self.add_suffix = add_suffix
        self.remove_suffix = remove_suffix
        self.spinner = Halo(
            text="Preparando operação de mover mensagens...", spinner="dots"
        )

    async def _get_file_size(self, message):
        # TODO - improv
        if message.audio:
            return message.audio.file_size
        if message.document:
            return message.document.file_size
        if message.photo:
            return message.photo.file_size
        if message.video:
            return message.video.file_size
        if message.voice:
            return message.voice.file_size
        if message.voice_note:
            return message.voice_note.file_size

    async def _create_group(self, client: Client, name: str, users_admin: list = None):
        chat_title = name.replace("-", " ").replace("_", " ")
        # TODO - prefix in config
        # TODO - vitrine
        new_channel = await client.create_channel(title=f"#DRIVE - {chat_title}")
        invite_link = await client.export_chat_invite_link(new_channel.id)
        new_description = f"{chat_title}\n\n📌 Link de Convite: {invite_link}"
        await client.set_chat_description(new_channel.id, new_description)

        if users_admin:
            # Adicionar user API
            await client.add_chat_members(new_channel.id, users_admin)
            for admin in users_admin:
                await client.promote_chat_member(
                    new_channel.id,
                    admin,
                    ChatPrivileges(
                        can_change_info=True,
                        can_delete_messages=True,
                        can_invite_users=True,
                        can_pin_messages=True,
                        can_restrict_members=True,
                        can_promote_members=True,
                        can_manage_video_chats=True,
                        can_post_messages=True,
                        can_edit_messages=True,
                        can_manage_chat=True,
                    ),
                )
        return new_channel

    async def _edit_forwarded_caption(self, forwarded_message, new_caption: str | None = None):
        if not forwarded_message:
            return

        try:
            await self.client.edit_message_caption(
                chat_id=self.destination_chat_id,
                message_id=forwarded_message.id,
                caption=new_caption,
            )
        except MessageNotModified:
            pass

    @staticmethod
    def _is_clone_video_message(message) -> bool:
        if message.video:
            return True
        doc = message.document
        return bool(doc and doc.mime_type and doc.mime_type.startswith("video/"))

    async def _video_send_extras(self, message, file_path: str, path_download: str) -> dict:
        """Thumb + metadados para send_video (evita preview preto / formato de documento)."""
        extras: dict = {}
        thumb_path = None
        if message and message.video and message.video.thumbs:
            thumb_path = await self.client.download_media(
                message.video.thumbs[0].file_id,
                file_name=f"{path_download}/{message.id}-tg-thumb.jpg",
            )
        elif message and message.document and message.document.thumbs:
            thumb_path = await self.client.download_media(
                message.document.thumbs[0].file_id,
                file_name=f"{path_download}/{message.id}-tg-thumb.jpg",
            )
        if not thumb_path and is_video_file(file_path):
            gen = f"{path_download}/{message.id}-gen-thumb.jpg"
            if await extract_video_thumbnail_jpeg(file_path, gen):
                thumb_path = gen
        if thumb_path:
            extras["thumb"] = thumb_path

        if message and message.video:
            v = message.video
            extras["duration"] = v.duration or 0
            extras["width"] = v.width or 0
            extras["height"] = v.height or 0
            if v.supports_streaming is not None:
                extras["supports_streaming"] = v.supports_streaming
        elif message and message.document and message.document.mime_type.startswith("video/"):
            w, h = await get_video_dimensions(file_path)
            dur = int(await get_video_duration(file_path))
            if dur > 0:
                extras["duration"] = dur
            if w > 0 and h > 0:
                extras["width"] = w
                extras["height"] = h
        return extras

    async def _download_clone_media(
        self,
        origin_chat_id: int,
        message_id: int,
        path_download: str,
        progress,
        progress_args: tuple,
    ):
        """Baixa mídia com mensagem fresca; renova file_reference se expirou."""
        last_exc: FileReferenceExpired | None = None
        for attempt in range(3):
            fresh = await self.client.get_messages(origin_chat_id, message_id)
            if fresh is None or getattr(fresh, "empty", False):
                logger.warning(
                    "Mensagem %s não encontrada ao obter referência de arquivo.",
                    message_id,
                )
                return None, None
            media_name = await self.get_media_name(fresh)
            try:
                file_path = await self.client.download_media(
                    fresh,
                    file_name=f"{path_download}/{message_id}-{media_name}",
                    progress=progress,
                    progress_args=progress_args,
                )
                return fresh, file_path
            except FileReferenceExpired as exc:
                last_exc = exc
                logger.warning(
                    "FILE_REFERENCE_EXPIRED na msg %s (tentativa %s/3); buscando mensagem de novo.",
                    message_id,
                    attempt + 1,
                )
                await asyncio.sleep(0.4 * (attempt + 1))
        if last_exc:
            raise last_exc
        return None, None

    async def run(self):
        self.spinner.start()
        try:
            # Obtém informações do chat de destino para verificar se o conteúdo é protegido.
            origin_chat = await self.client.get_chat(self.origin_chat_id)
            path_download = create_path(f"./downloads/{origin_chat.title}")
            protected = origin_chat.has_protected_content
            description_destination = f"| Destino: {self.destination_chat_id}" if self.destination_chat_id else ''
            self.spinner.succeed(
                f"Clonando => {origin_chat.title} ({origin_chat.id}) {description_destination} | Protected: {protected}"
            ).start()
        except PeerIdInvalid as e:
            # Recupera os chats atuais do cliente e tenta novamente
            current_chats = await self.get_current_chats()
            if self.destination_chat_id not in current_chats:
                self.spinner.fail(f"Chat de destino não encontrado").start()
                return
            return await self.run()
        except Exception as e:
            self.spinner.fail(f"Erro ao obter chat de destino: {e}").start()
            return

        # TODO - users admin in config
        # Caso não tenha destino cria grupo
        if not self.destination_chat_id:
            self.spinner.text = f"Criando grupo de destino..."
            destination_chat = await self._create_group(
                client=self.client,
                name=origin_chat.title,
                users_admin=self.config['admins'].split(','),
            )
            self.destination_chat_id = destination_chat.id
            self.spinner.succeed(f"Grupo de destino criado: {destination_chat.title} ({destination_chat.id})").start()
        # Caso tenha destino, obter grupo
        else:
            self.spinner.text = f"Obtendo grupo de destino..."
            destination_chat = await self.client.get_chat(self.destination_chat_id)
            self.spinner.succeed(f"Grupo de destino encontrado: {destination_chat.title} ({destination_chat.id})").start()

        # Recupera o último message_id processado (caso haja retomada)
        last_msg_id = self.progress_tracker.get_last_message_id(
            op="clone", chat_id=origin_chat.id, dest_chat_id=destination_chat.id
        )
        self.spinner.succeed(f"Retomando a partir do message_id: {last_msg_id}").start()
        logger.info(f"Retomando a partir do message_id: {last_msg_id}")

        # Configure a barra de progresso
        self.spinner.text = "Obtendo mensagens"

        # Itera sobre o histórico do chat de origem.
        try:
            messages = await get_chat_history(
                client=self.client,
                origin_chat_id=origin_chat.id,
                from_msg_id=last_msg_id,
            )

            total_movidos = 0
            if messages is None or len(messages) == 0:
                self.spinner.warn(f"Nenhuma mensagem encontrada em {origin_chat.id}")
                return
            total_messages = len(messages)
            self.spinner.text = f"Clonando mensagens 0/{total_messages}"
            for message in messages:
                try:
                    # Ignora mensagens de serviço
                    # if isinstance(message, MessageService):
                    #     continue

                    ## Adicionar ou remover sufixo
                    if self.add_suffix:
                        logger.debug(f"Adicionando sufixo: {self.add_suffix}")
                        message.text = f"{message.text} {self.add_suffix}"
                        message.caption = f"{message.caption} {self.add_suffix}"
                        logger.debug(f"Texto final: {message.text}")
                        logger.debug(f"Caption final: {message.caption}")
                    if self.remove_suffix:
                        logger.debug(f"Removendo sufixo: {self.remove_suffix}")
                        message.text = message.text.replace(self.remove_suffix, "") if message.text else None
                        message.caption = message.caption.replace(self.remove_suffix, "") if message.caption else None
                        logger.debug(f"Texto final: {message.text}")
                        logger.debug(f"Caption final: {message.caption}")
                    # Se o chat de destino tiver conteúdo protegido, não é possível encaminhar;
                    # portanto, copiamos o conteúdo manualmente.
                    if protected:
                        if message.media:
                            # Baixa o arquivo da mídia
                            def progress(current, total, args):
                                total_mb = (total / 1024) / 1024
                                current_mb = (current / 1024) / 1024
                                self.spinner.text = (
                                    f"{args[0]} {current_mb:.2f}/{total_mb:.2f}MB"
                                )
                            media_for_file, file_path = await self._download_clone_media(
                                origin_chat.id,
                                message.id,
                                path_download,
                                progress,
                                ([f"Baixando mensagem ID{message.id} |"],),
                            )
                            if file_path is None:
                                logger.warning(
                                    f"Falha ao baixar mídia da mensagem {message.id}"
                                )
                                continue
                            
                            send_extras: dict = {}
                            if self._is_clone_video_message(media_for_file):
                                logger.info("Verificando se o vídeo precisa de reencode")
                                video_codec = await get_codec(file_path, "v")
                                audio_codec = await get_codec(file_path, "a")
                                logger.debug(f"Video codec: {video_codec}")
                                logger.debug(f"Audio codec: {audio_codec}")
                                if needs_reencode(
                                    video_codec, audio_codec, file_path
                                ):
                                    self.spinner.text = "Reencodando vídeo..."
                                    cmd = build_ffmpeg_cmd(
                                        file_path=file_path,
                                        output_path=file_path,
                                        video_codec=video_codec,
                                        audio_codec=audio_codec,
                                    )
                                    proc = await asyncio.create_subprocess_exec(*cmd)
                                    await proc.communicate()
                                    if proc.returncode != 0:
                                        logger.error(
                                            f"Erro ao reencodar vídeo: {proc.stderr.decode()}"
                                        )
                                        continue
                                    self.spinner.succeed("Vídeo reencodado com sucesso.")
                                send_extras = await self._video_send_extras(
                                    media_for_file, file_path, path_download
                                )
                            await super().send(
                                chat_id=self.destination_chat_id,
                                message=media_for_file,
                                document=file_path,
                                caption=message.caption or "",
                                progress=progress,
                                progress_args=(
                                    [f"Enviando mensagem ID{message.id} |"],
                                ),
                                **send_extras,
                            )

                        else:
                            # Se for apenas texto, envia a mensagem
                            await self.client.send_message(
                                self.destination_chat_id,
                                message.text or message.caption or "",
                            )
                    else:
                        # Se o chat não tiver conteúdo protegido, encaminha a mensagem
                        forwarded_message = await self.client.forward_messages(
                            chat_id=self.destination_chat_id,
                            from_chat_id=origin_chat.id,
                            message_ids=message.id,
                            drop_author=True,
                        )
                        if self.add_suffix or self.remove_suffix:
                            await self._edit_forwarded_caption(forwarded_message, message.text or message.caption or "")
                        
                    logger.info(f"Mensagem {message.id} processada com sucesso.")
                    time.sleep(2)
                except (MessageIdInvalid, MessageEmpty):
                    pass
                except Exception as msg_err:
                    logger.error(f"Erro ao processar mensagem {message.id}: {msg_err}")
                    # Pode-se registrar o erro e continuar
                    raise

                # Atualiza o progresso (para retomar no caso de interrupção)
                self.progress_tracker.update(
                    "clone", origin_chat.id, self.destination_chat_id, message.id
                )

                total_movidos += 1
                self.spinner.text = (
                    f"Clonando mensagens {total_movidos}/{total_messages}"
                )

        except Exception as e:
            logger.error(f"Erro ao iterar sobre o histórico de mensagens: {e}")
            raise
        finally:
            self.spinner.succeed("Operação de mover mensagens concluída.")
