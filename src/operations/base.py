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

    @staticmethod
    def _mime_is_video(mime_type: str | None) -> bool:
        return bool(mime_type and mime_type.startswith("video/"))

    async def send(self, message, *args, **kwargs):
        if message.video:
            video = kwargs.pop('document')
            v = message.video
            send_video_kwargs = {
                "duration": v.duration or 0,
                "width": v.width or 0,
                "height": v.height or 0,
                "supports_streaming": True
                if v.supports_streaming is None
                else v.supports_streaming,
            }
            if v.file_name:
                send_video_kwargs["file_name"] = v.file_name
            send_video_kwargs.update(kwargs)
            return await self.client.send_video(video=video, *args, **send_video_kwargs)

        if message.audio:
            audio = kwargs.pop('document')
            return await self.client.send_audio(audio=audio, *args, **kwargs)

        # Vídeo enviado como "arquivo" vem só como document com mime video/* — send_document vira anexo sem preview.
        if message.document and self._mime_is_video(message.document.mime_type):
            video = kwargs.pop('document')
            doc = message.document
            send_video_kwargs = {"supports_streaming": True}
            if doc.file_name:
                send_video_kwargs["file_name"] = doc.file_name
            send_video_kwargs.update(kwargs)
            return await self.client.send_video(video=video, *args, **send_video_kwargs)

        if message.document or message.voice:
            return await self.client.send_document(*args, **kwargs)
        if message.photo:
            photo = kwargs.pop('document')
            return await self.client.send_photo(photo=photo, *args, **kwargs)
        if message.video_note:
            video_note = kwargs.pop('document')
            kwargs.pop('caption')
            return await self.client.send_video_note(video_note=video_note, *args, **kwargs)
        if message.animation:
            animation = kwargs.pop('document')
            return await self.client.send_animation(animation=animation, *args, **kwargs)
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

    async def get_current_chats(self) -> list[int]:
        """
        Obtém os chats atuais do cliente e evita o erro
        400 PEER_ID_INVALID - chat não encontrado 
        ao obter o chat de destino.
        """
        chat_ids: list[int] = []
        async for dialog in self.client.get_dialogs():
            chat_ids.append(dialog.chat.id)
        return chat_ids