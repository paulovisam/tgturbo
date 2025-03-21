###############################################################################
# Classe base para operações (possibilita escalabilidade com novos métodos)
###############################################################################
from pyrogram.client import Client
from src.progress_tracker import ProgressTracker

class BaseOperation:
    def __init__(self, client: Client, progress_tracker: ProgressTracker):
        self.client = client
        self.progress_tracker = progress_tracker
        self.config = None

    async def send(self, message, *args, **kwargs):
        if message.document or message.voice:
            return await self.client.send_document(*args, **kwargs)
        if message.audio:
            return await self.client.send_audio(*args, **kwargs)
        if message.video:
            return await self.client.send_video(*args, **kwargs)
        if message.photo:
            # photo = kwargs.get('document')
            photo = kwargs.pop('document')
            return await self.client.send_photo(photo=photo, *args, **kwargs)
        if message.video_note:
            video_note = kwargs.pop('document')
            kwargs.pop('caption')
            return await self.client.send_video_note(video_note=video_note, *args, **kwargs)
        if message.animation:
            animation = kwargs.pop('document')
            return await self.client.send_animation(animation=animation*args, **kwargs)
        if message.sticker:
            kwargs.pop('caption')
            sticker = kwargs.pop('document')
            return await self.client.send_sticker(sticker=sticker, *args, **kwargs)
        if message.location:
            return await self.client.send_location(*args, **kwargs)
        if message.contact:
            return await self.client.send_contact(*args, **kwargs)
        return await self.client.send_message(*args, **kwargs)
    
    async def get_media_name(self, message):
        if message.document:
            return message.document.file_name
        if message.audio:
            return f"{message.audio.file_name or message.audio.file_unique_id}.mp3"
        if message.video:
            return message.video.file_name
        if message.voice:
            mime_type = message.voice.mime_type.split("/")[-1]
            return f"{message.voice.file_unique_id}.{mime_type}"
        if message.video_note:
            mime_type = message.video_note.mime_type.split("/")[-1]
            return f"{message.video_note.file_unique_id}.{mime_type}"
        if message.photo:
            return f"{message.photo.file_unique_id}.png"
        if message.animation:
            mime_type = message.animation.mime_type.split("/")[-1]
            name = message.animation.file_name or message.animation.file_unique_id
            return f"{name}.{mime_type}"
        if message.sticker:
            mime_type = message.sticker.mime_type.split("/")[-1]
            name = message.sticker.file_name or message.sticker.file_unique_id
            return f"{name}.{mime_type}"