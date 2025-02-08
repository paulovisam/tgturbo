from .base import BaseOperation
from pyrogram.client import Client
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path


class MediaDownloader(BaseOperation):
    """Operação: Baixar mídias de um grupo"""

    def __init__(self, client: Client, chat_id: int, progress_tracker: ProgressTracker):
        super().__init__(client, progress_tracker)
        self.chat_id = chat_id
        self.spinner = Halo(
            text="Preparando operação de download de mídias...", spinner="dots"
        )
        self.spinner.start()

    async def run(self):

        chat = self.client.get_chat(self.chat_id)
        path_download = create_path(f"./downloads/{chat.title}")

        # Recupera o último message_id processado (para retomar)
        last_msg_id = self.progress_tracker.get_last_message_id(
            op="download", chat_id=self.chat_id
        )
        self.spinner.succeed(f"Baixando {chat.title}").start()
        if last_msg_id > 0:
            msg = f"Retomando download a partir do message_id: {last_msg_id}"
            self.spinner.info(msg).start()
            logger.info(msg)

        try:
            messages = []
            async for message in self.client.get_chat_history(
                self.origin_chat_id,
                offset_id=last_msg_id,
            ):
                messages.append(message)
            messages.reverse()

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

                        file_path = await self.client.download_media(
                            message,
                            file_name=path_download,
                            progress=progress,
                            progress_args=([f"Baixando mensagem ID{message.id} |"],),
                        )
                        if file_path:
                            logger.info(
                                f"Mídia da mensagem {message.message_id} baixada em {file_path}"
                            )
                        else:
                            logger.warning(
                                f"Falha ao baixar mídia da mensagem {message.message_id}"
                            )
                    except Exception as media_err:
                        logger.error(
                            f"Erro ao baixar mídia da mensagem {message.message_id}: {media_err}"
                        )
                # Atualiza o progresso
                self.progress_tracker.update(
                    "download", self.chat_id, None, message.message_id
                )
                total_download += 1
        except Exception as e:
            logger.error(f"Erro ao iterar sobre o histórico do chat: {e}")
        finally:
            self.spinner.succeed("Operação de download de mídias concluída.")
