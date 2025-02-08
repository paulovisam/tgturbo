import os


def create_path(path: str):
    if not os.path.exists(path):
        os.makedirs(path)
    return path

async def get_chat_history(client, origin_chat_id, last_msg_id):
    messages = []
    async for message in client.get_chat_history(
            origin_chat_id,
            offset_id=last_msg_id,
    ):
        messages.append(message)
    messages.reverse()
    return messages 