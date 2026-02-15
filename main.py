import asyncio

from pyrogram import Client
from src.log import logger
from src.progress_tracker import ProgressTracker

from src.operations.media_clone import MediaClone
from src.operations.media_downloader import MediaDownloader
from src.operations.media_download_single import MediaDownloadSingle
from src.operations.media_downup import MediaDownUp
from src.operations.media_upload import MediaUpload
from src.interface.menu import menu
from src.schemas import InputModel
import os

#TODO - Verificar se já existe arquivo antes de baixar

async def main():
    # Função principal e configuração da linha de comando
    args = await menu()

    # Cria o rastreador de progresso
    progress_tracker = ProgressTracker()

    if not args.confirm:
        return await main()
    
    # Crie e inicie o cliente Pyrogram. Altere "my_account" conforme sua sessão/configuração.
    async with Client("user") as client:
        if args.action == "clone":
            action = MediaClone(
                client=client,
                origin_chat_id=args.origin_id,
                destination_chat_id=args.dest_id,
                progress_tracker=progress_tracker,
            )

        elif args.action == "download chat":
            action = MediaDownloader(
                client=client,
                origin_chat_id=args.origin_id,
                progress_tracker=progress_tracker
            )
        elif args.action == "download media":
            action = MediaDownloadSingle(
                client=client,
                origin_link=args.origin_id,
                progress_tracker=progress_tracker
            )
        elif args.action == "upload":
            action = MediaUpload(
                client=client,
                upload_path=args.upload_path,
                destination_chat_id=args.dest_id,
                progress_tracker=progress_tracker,
            )
        elif args.action == "down_up":
            action = MediaDownUp(
                client=client,
                origin_chat_id=args.origin_id,
                destination_chat_id=args.dest_id,
                progress_tracker=progress_tracker,
            )

        if action:
            await action.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrompido pelo usuário.")
