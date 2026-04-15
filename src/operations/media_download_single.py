from .base import BaseOperation
from pyrogram.client import Client
from pyrogram.errors import FileReferenceExpired
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path, get_chat_history
import asyncio


class MediaDownloadSingle(BaseOperation):
    """Operação: Baixar mídia de um link"""

    def __init__(self, client: Client, origin_link: str, progress_tracker: ProgressTracker):
        super().__init__(client, progress_tracker)
        self.origin_link = origin_link
        self.spinner = Halo(
            text="Preparando operação de download de mídia...", spinner="dots"
        )
        self.spinner.start()
    
    async def run(self):
        try:
            def progress(current, total, args):
                total_mb = (total / 1024) / 1024
                current_mb = (current / 1024) / 1024
                self.spinner.text = (
                    f"{args[0]} {current_mb:.2f}/{total_mb:.2f}MB"
                )

            chat_id, message_id = self.origin_link.split('/')[-2:]
            chat_id = f"-100{chat_id}"
            message_id = int(message_id)
            chat = await self.client.get_chat(chat_id)
            path_download = create_path(f"./downloads/{chat.title}")
            file_path = None
            message = None
            for attempt in range(3):
                message = await self.client.get_messages(chat_id, message_id)
                if message is None or getattr(message, "empty", False):
                    logger.error("Mensagem não encontrada: %s", message_id)
                    break
                media_name = await super().get_media_name(message)
                try:
                    file_path = await self.client.download_media(
                        message=message,
                        file_name=f"{path_download}/{message.id}-{media_name}",
                        progress=progress,
                        progress_args=(
                            [f"Baixando mensagem ID{message.id} |"],
                        ),
                    )
                    break
                except FileReferenceExpired:
                    logger.warning(
                        "FILE_REFERENCE_EXPIRED (tentativa %s/3); renovando mensagem.",
                        attempt + 1,
                    )
                    await asyncio.sleep(0.4 * (attempt + 1))
            mid = message.id if message else message_id
            if file_path:
                logger.info(
                    f"Mídia da mensagem {mid} baixada em {file_path}"
                )
            else:
                logger.warning(
                    f"Falha ao baixar mídia da mensagem {mid}"
                )
        except Exception as e:
            logger.error(f"Erro ao baixar mídia: {e}")
            raise e