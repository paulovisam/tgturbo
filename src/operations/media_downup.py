from .base import BaseOperation
from pyrogram.client import Client
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path, get_chat_history


class MediaDownUp(BaseOperation):
    """Operação: Baixar mídias de um grupo"""

    def __init__(self, client: Client, origin_chat_id: int, destination_chat_id: int, progress_tracker: ProgressTracker):
        super().__init__(client, progress_tracker)
        self.origin_chat_id = origin_chat_id
        self.destination_chat_id = destination_chat_id
        self.spinner = Halo(
            text="Preparando operação de download e envio de mídias...", spinner="dots"
        )
        self.spinner.start()

    async def run(self):

        chat = await self.client.get_chat(self.origin_chat_id)
        path_download = create_path(f"./downloads/{chat.title}")

        # Recupera o último message_id processado (para retomar)
        last_msg_id = self.progress_tracker.get_last_message_id(
            op="download", chat_id=self.origin_chat_id
        )
        self.spinner.succeed(f"Baixando {chat.title}").start()
        if last_msg_id > 0:
            msg = f"Retomando download a partir do message_id: {last_msg_id}"
            self.spinner.info(msg).start()
            logger.info(msg)

        try:
            messages = await get_chat_history(
                client=self.client,
                origin_chat_id=self.origin_chat_id,
                from_msg_id=last_msg_id,
            )

            total_messages = len(messages)
            total_download = 0
            if total_messages == 0:
                self.spinner.warn(
                    f"Nenhuma mensagem encontrada em {self.origin_chat_id}"
                )
                return

            self.spinner.text = f"Baixando mensagens 0/{total_messages}"
            for message in messages:
                if message.media:
                    try:
                        def progress(current, total, args):
                            total_mb = (total / 1024) / 1024
                            current_mb = (current / 1024) / 1024
                            self.spinner.text = (
                                f"{args[0]} {current_mb:.2f}/{total_mb:.2f}MB"
                            )
                        media_name = await super().get_media_name(message)
                        #Atualizar mensagem para obter o caminho do arquivo
                        message = await self.client.get_messages(
                            chat_id=self.origin_chat_id,
                            message_ids=message.id,
                        )
                        file_path = await self.client.download_media(
                            message=message,
                            file_name=f'{path_download}/{message.id}-{media_name}',
                            progress=progress,
                            progress_args=([f"Baixando mensagem ID{message.id} |"],),
                        )
                        if file_path:
                            logger.info(
                                f"Mídia da mensagem {message.id} baixada em {file_path}"
                            )
                            self.spinner.text = ("Enviando mídia para o chat de destino...")
                            sent_message = await super().send(
                                message=message,
                                chat_id=self.destination_chat_id,
                                document=file_path,
                                caption=message.text or "",
                                progress=progress,
                                progress_args=([f"Enviando mensagem ID{message.id} |"],)
                            )
                            if sent_message:
                                logger.info(
                                    f"Mídia enviada para o chat de destino com ID {sent_message.id}"
                                )
                        else:
                            logger.warning(
                                f"Falha ao baixar mídia da mensagem {message.id}"
                            )
                    except Exception as media_err:
                        logger.error(
                            f"Erro ao baixar mídia da mensagem {message.id}: {media_err}"
                        )
                        raise media_err
                # Atualiza o progresso
                self.progress_tracker.update(
                    op="download",
                    chat_id=self.origin_chat_id,
                    dest_chat_id=self.destination_chat_id,
                    message_id=message.id
                )
                total_download += 1
        except Exception as e:
            logger.error(f"Erro ao iterar sobre o histórico do chat: {e}")
            raise e
        finally:
            self.spinner.succeed("Operação de download de mídias concluída.")
