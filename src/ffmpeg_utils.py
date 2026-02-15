"""Funções utilitárias assíncronas para operações com FFmpeg/FFprobe."""

import os
import asyncio
from pathlib import Path
from src.log import logger

VIDEO_EXTENSIONS = [
    '.mp4', '.ts', '.mpg', '.mpeg', '.avi', '.mkv', '.flv', '.3gp',
    '.rmvb', '.webm', '.vob', '.ogv', '.rrc', '.gifv', '.mng',
    '.mov', '.qt', '.wmv', '.yuv', '.rm', '.asf', '.amv', '.m4p',
    '.m4v', '.mp2', '.mpe', '.mpv', '.svi', '.3g2',
    '.mxf', '.roq', '.nsv', '.f4v', '.f4p', '.f4a', '.f4b'
]

TARGET_VIDEO_CODEC = "h264"
TARGET_AUDIO_CODEC = "aac"
TARGET_EXTENSION = ".mp4"


async def get_codec(file_path: str, stream_type: str) -> str:
    """Obtém o codec de um stream (v=video, a=audio) usando ffprobe."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', f'{stream_type}:0',
        '-show_entries', 'stream=codec_name',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode('utf-8').strip()


async def has_duration(file_path: str) -> bool:
    """Verifica se o arquivo de vídeo possui duração válida."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    return stdout.decode('utf-8').strip() != ''


async def file_is_corrupted(file_path: str) -> bool:
    """Verifica se o arquivo de vídeo está corrompido."""
    cmd = ['ffprobe', '-v', 'error', '-i', file_path]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    return b'moov atom not found' in stderr or proc.returncode != 0


def is_video_file(file_path: str) -> bool:
    """Verifica se o arquivo é um vídeo com base na extensão."""
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


def needs_reencode(video_codec: str, audio_codec: str, file_path: str) -> bool:
    """Verifica se o vídeo precisa ser reencodado para H264/AAC MP4."""
    is_target_codecs = (
        video_codec == TARGET_VIDEO_CODEC and audio_codec == TARGET_AUDIO_CODEC
    )
    is_target_ext = file_path.lower().endswith(TARGET_EXTENSION)
    return not (is_target_codecs and is_target_ext)


def build_ffmpeg_cmd(
    file_path: str, output_path: str,
    video_codec: str, audio_codec: str
) -> list[str]:
    """Constrói o comando ffmpeg para conversão do vídeo."""
    cmd = [
        'ffmpeg', '-v', 'quiet', '-stats', '-y',
        '-i', file_path,
        '-b:a', '128k',
        '-hide_banner'
    ]

    needs_video = video_codec != TARGET_VIDEO_CODEC
    needs_audio = audio_codec != TARGET_AUDIO_CODEC

    if not needs_video and not needs_audio:
        # Apenas remuxar (extensão diferente, codecs já corretos)
        cmd.extend(['-c:v', 'copy', '-c:a', 'copy'])
    elif needs_video and not needs_audio:
        cmd.extend([
            '-c:v', 'libx264', '-preset', 'ultrafast',
            '-threads', '2', '-c:a', 'copy',
            '-crf', '23', '-maxrate', '4M',
        ])
    elif not needs_video and needs_audio:
        cmd.extend(['-c:v', 'copy', '-c:a', 'aac'])
    else:
        cmd.extend([
            '-c:v', 'libx264', '-c:a', 'aac',
            '-preset', 'ultrafast', '-threads', '2',
            '-crf', '23', '-maxrate', '4M',
        ])

    cmd.append(output_path)
    return cmd
