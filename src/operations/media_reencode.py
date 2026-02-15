import os
import asyncio
from pathlib import Path
from .base import BaseOperation
from pyrogram.client import Client
from halo import Halo
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.ffmpeg_utils import (
    TARGET_EXTENSION,
    get_codec, has_duration, file_is_corrupted,
    is_video_file, needs_reencode, build_ffmpeg_cmd,
)


class MediaReencode(BaseOperation):
    """Operação: Reencodar vídeos de uma pasta para H264/AAC MP4"""

    def __init__(
        self,
        client: Client,
        folder_path: str,
        progress_tracker: ProgressTracker,
    ):
        super().__init__(client, progress_tracker)
        self.folder_path = folder_path
        self.spinner = Halo(
            text="Preparando operação de reencode de vídeos...", spinner="dots"
        )

    async def _delete_corrupted_videos(self) -> int:
        """Remove vídeos corrompidos ou sem duração válida da pasta."""
        folder = Path(self.folder_path)
        removed = 0
        list_invalid_videos = []            
        for path in folder.rglob('*'):
            if not path.is_file() or not is_video_file(str(path)):
                continue

            valid_duration = await has_duration(str(path))
            corrupted = await file_is_corrupted(str(path))

            if not valid_duration or corrupted:
                list_invalid_videos.append(str(path))

        if list_invalid_videos:
            answer = input("Existem vídeos corrompidos, deseja pagar? (s/n) ")
            if answer.lower() == "s":
                for video in list_invalid_videos:
                    os.remove(video)
                    removed += 1
                    logger.warning(f"Removendo vídeo inválido: {video}")
                    self.spinner.text = f"Removendo vídeo corrompido: {video.name}"
        if removed > 0:
            self.spinner.info(
                f"{removed} vídeo(s) corrompido(s) removido(s)"
            ).start()

        return removed

    async def _scan_videos_to_convert(self) -> list[dict]:
        """Escaneia a pasta e retorna lista de vídeos que precisam de conversão."""
        videos: list[dict] = []

        for subdir, _, files in os.walk(self.folder_path):
            for file in files:
                file_path = os.path.join(subdir, file)
                if not is_video_file(file_path):
                    continue
                try:
                    video_codec = await get_codec(file_path, 'v')
                    audio_codec = await get_codec(file_path, 'a')

                    if needs_reencode(video_codec, audio_codec, file_path):
                        videos.append({
                            'path': file_path,
                            'video_codec': video_codec,
                            'audio_codec': audio_codec,
                        })
                except Exception as e:
                    logger.error(f"Erro ao verificar codec de {file_path}: {e}")

        return videos

    async def _convert_file(self, file_info: dict) -> str | None:
        """Converte um único arquivo de vídeo para H264/AAC MP4."""
        file_path = file_info['path']
        video_codec = file_info['video_codec']
        audio_codec = file_info['audio_codec']

        file_name, _ = os.path.splitext(file_path)
        output_path = f"{file_name}{TARGET_EXTENSION}"

        # Se o output é o mesmo que o input, usar arquivo temporário
        temp_output = None
        if output_path == file_path:
            temp_output = f"{file_name}_reencode{TARGET_EXTENSION}"
            output_path = temp_output

        cmd = build_ffmpeg_cmd(file_path, output_path, video_codec, audio_codec)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"Erro ao converter {file_path}: {stderr.decode()}")
            if os.path.exists(output_path):
                os.remove(output_path)
            return None

        # Remover arquivo original
        if os.path.exists(file_path):
            os.remove(file_path)

        # Se usou arquivo temporário, renomear para o path final
        if temp_output and os.path.exists(temp_output):
            final_path = f"{file_name}{TARGET_EXTENSION}"
            os.rename(temp_output, final_path)
            output_path = final_path

        logger.info(f"Vídeo convertido: {output_path}")
        return output_path

    async def run(self):
        self.spinner.start()

        if not os.path.exists(self.folder_path):
            self.spinner.fail(f"Pasta não encontrada: {self.folder_path}")
            return

        try:
            # 1. Remover vídeos corrompidos
            self.spinner.text = "Verificando vídeos corrompidos..."
            await self._delete_corrupted_videos()


            # 2. Escanear vídeos que precisam de conversão
            self.spinner.text = "Verificando vídeos para conversão..."
            videos_to_convert = await self._scan_videos_to_convert()
            total = len(videos_to_convert)

            if total == 0:
                self.spinner.succeed(
                    "Todos os vídeos já estão no formato correto (H264/AAC MP4)."
                )
                return

            self.spinner.info(
                f"{total} vídeo(s) precisam ser convertidos."
            ).start()

            # 3. Converter cada vídeo
            converted = 0
            errors = 0

            for video_info in videos_to_convert:
                file_name = os.path.basename(video_info['path'])
                self.spinner.text = (
                    f"Convertendo {converted + 1}/{total}: {file_name}"
                )

                result = await self._convert_file(video_info)
                if result:
                    converted += 1
                else:
                    errors += 1

            # 4. Relatório final
            msg = f"Reencode concluído: {converted}/{total} convertidos"
            if errors > 0:
                msg += f" ({errors} erro(s))"
            self.spinner.succeed(msg)

        except Exception as e:
            logger.error(f"Erro durante reencode: {e}")
            self.spinner.fail(f"Erro durante reencode: {e}")
            raise
