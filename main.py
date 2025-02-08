import asyncio

from pyrogram import Client
from src.log import logger
from src.progress_tracker import ProgressTracker

from src.operations.media_clone import MediaClone
from src.operations.media_downloader import MediaDownloader
from src.interface.menu import menu


async def main():
    # Função principal e configuração da linha de comando
    args = await menu()

    # Cria o rastreador de progresso
    progress_tracker = ProgressTracker()

    # Crie e inicie o cliente Pyrogram. Altere "my_account" conforme sua sessão/configuração.
    async with Client("user") as client:
        if args.action == "clone":
            # args.origin_id = 'https://t.me/+wG-XmNSxUXwxZTAx'
            args.origin_id = 'https://t.me/+1R6h0lBM2CM3MDFh'
            mover = MediaClone(
                client=client,
                origin_chat_id=args.origin_id,
                destination_chat_id=args.dest_id,
                progress_tracker=progress_tracker,
            )
            await mover.run()
        elif args.action == "download":
            downloader = MediaDownloader(
                client=client, chat_id=args.origin_id, progress_tracker=progress_tracker
            )
            await downloader.run()
        elif args.action == "upload":
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script interrompido pelo usuário.")
