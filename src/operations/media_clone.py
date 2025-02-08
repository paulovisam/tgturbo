import os, time
from .base import BaseOperation
from pyrogram.client import Client
from pyrogram.types import ChatPrivileges
from pyrogram.errors import MessageIdInvalid, MessageEmpty
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path, get_chat_history


class MediaClone(BaseOperation):
    """Operação: Mover mensagens de um grupo para outro"""

    def __init__(
        self,
        client: Client,
        origin_chat_id: int,
        destination_chat_id: int,
        progress_tracker: ProgressTracker,
    ):
        super().__init__(client, progress_tracker)
        self.client = client
        self.origin_chat_id = origin_chat_id
        self.destination_chat_id = destination_chat_id
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
        # TODO -  prefix in config
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

    async def run(self):
        self.spinner.start()

        try:
            # Obtém informações do chat de destino para verificar se o conteúdo é protegido.
            origin_chat = await self.client.get_chat(self.origin_chat_id)
            path_download = create_path(f"./downloads/{origin_chat.title}")
            protected = origin_chat.has_protected_content
            self.spinner.succeed(
                f"Clonando => Chat de origem ({origin_chat.id}) | Chat de destino ({self.destination_chat_id}) Protected: {protected}"
            ).start()
        except Exception as e:
            self.spinner.fail(f"Erro ao obter chat de destino: {e}").start()
            return

        # TODO - users admin in config
        # Caso não tenha destino cria grupo
        if not self.destination_chat_id:
            destination_chat = await self._create_group(
                client=self.client, name=origin_chat.title, users_admin=None
            )
            self.destination_chat_id = destination_chat.id
        # Caso tenha destino, obter grupo
        else:
            destination_chat = self.client.get_chat(self.destination_chat_id)

        # Recupera o último message_id processado (caso haja retomada)
        last_msg_id = self.progress_tracker.get_last_message_id(
            op="clone", chat_id=origin_chat.id, dest_chat_id=destination_chat.id
        )
        logger.info(f"Retomando a partir do message_id: {last_msg_id}")

        # Configure a barra de progresso
        self.spinner.text = "Obtendo mensagens"

        # Itera sobre o histórico do chat de origem.
        try:
            messages = await get_chat_history(
                client=self.client,
                origin_chat_id=origin_chat.id,
                last_msg_id=last_msg_id,
            )

            total_movidos = 0
            if messages is None or len(messages) == 0:
                self.spinner.warn(f"Nenhuma mensagem encontrada em {origin_chat.id}")
                return
            total_messages = len(messages)
            self.spinner.text = f"Clonando mensagens 0/{total_messages}"
            for message in messages:
                try:
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

                            file_path = await self.client.download_media(
                                message,
                                file_name=path_download,
                                progress=progress,
                                progress_args=(
                                    [f"Baixando mensagem ID{message.id} |"],
                                ),
                            )
                            if file_path is None:
                                logger.warning(
                                    f"Falha ao baixar mídia da mensagem {message.id}"
                                )
                                continue

                            # Envia a mídia para o chat de destino.
                            # Você pode personalizar: se a mídia for foto, use send_photo, etc.
                            # if message.media.DOCUMENT:
                            await self.client.send_document(
                                chat_id=self.destination_chat_id,
                                document=file_path,
                                caption=message.caption or "",
                                progress=progress,
                                progress_args=(
                                    [f"Enviando mensagem ID{message.id} |"],
                                ),
                            )

                        else:
                            # Se for apenas texto, envia a mensagem
                            await self.client.send_message(
                                self.destination_chat_id,
                                message.text or message.caption or "",
                            )
                    else:
                        # Se o chat não tiver conteúdo protegido, encaminha a mensagem
                        await self.client.forward_messages(
                            chat_id=self.destination_chat_id,
                            from_chat_id=origin_chat.id,
                            message_ids=message.id,
                        )
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
