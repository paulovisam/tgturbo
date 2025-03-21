import os
from pyrogram.client import Client


def create_path(path: str):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

async def get_chat_history(client: Client, origin_chat_id: int | str, from_msg_id: int | str) -> list:
    messages = []
    async for message in client.get_chat_history(origin_chat_id):
        if message.id <= from_msg_id:
            break
        messages.append(message)
    messages.reverse()
    return messages