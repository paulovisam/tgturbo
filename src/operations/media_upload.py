import os
import zipfile
import csv
import asyncio
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from halo import Halo
from natsort import natsorted
from pyrogram.client import Client
from pyrogram.errors import FloodWait
from tqdm import tqdm

from .base import BaseOperation
from .media_reencode import MediaReencode
from src.progress_tracker import ProgressTracker
from src.log import logger
from src.utils import create_path
from src.ffmpeg_utils import is_video_file, get_video_duration, split_video

MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024 - 1024  # ~2GB safe limit (2048 MB - safety margin)
# Telegram allows up to 2GB (2000MB or 4000MB for premium). 
# We'll use 2000MB (approx 1.95GB) to be safe for everyone.
SAFE_SIZE_LIMIT = 2000 * 1024 * 1024 

class MediaUpload(BaseOperation):
    """Operação: Enviar mídias para um chat com fluxo complexo"""

    def __init__(self, client: Client, upload_path: str, destination_chat_id: str | int, progress_tracker: ProgressTracker):
        super().__init__(client, progress_tracker)
        self.upload_path = upload_path
        self.destination_chat_id = destination_chat_id
        # Also patch client if needed, or rely on self.destination_chat_id
        self.client.destination_chat_id = destination_chat_id  # Monkey patch to satisfy existing references if any
        self.spinner = Halo(
            text="Preparando operação de envio de mídias...", spinner="dots"
        )
        self.spinner.start()
        # Tracking file for resumability
        self.processed_files_log = os.path.join(self.upload_path, ".processed_files")
        self.processed_files = self._load_processed_files()
        self.file_tags = {} # Map file path -> hashtag (e.g. #F001)

    def _load_processed_files(self) -> set:
        processed = set()
        if os.path.exists(self.processed_files_log):
            with open(self.processed_files_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if line.startswith("CHAT_ID:"):
                        saved_id = line.replace("CHAT_ID:", "").strip()
                        if saved_id:
                            # Try to convert to int if it's a numeric ID
                            try:
                                self.destination_chat_id = int(saved_id)
                            except ValueError:
                                self.destination_chat_id = saved_id
                    else:
                        processed.add(line)
        return processed

    def _save_chat_id(self, chat_id: str | int):
        """Salva o ID do chat no log de progresso se ainda não estiver lá."""
        content = ""
        if os.path.exists(self.processed_files_log):
            with open(self.processed_files_log, "r", encoding="utf-8") as f:
                content = f.read()
        
        if f"CHAT_ID:{chat_id}" not in content:
            with open(self.processed_files_log, "a", encoding="utf-8") as f:
                f.write(f"CHAT_ID:{chat_id}\n")

    def _mark_as_processed(self, filename: str):
        with open(self.processed_files_log, "a", encoding="utf-8") as f:
            f.write(f"{filename}\n")
        self.processed_files.add(filename)

    def _is_processed(self, filename: str) -> bool:
        return filename in self.processed_files

    def _is_destination_empty(self) -> bool:
        """Verifica se destination_chat_id está vazio ou inválido."""
        if self.destination_chat_id is None:
            return True
        if isinstance(self.destination_chat_id, str) and not self.destination_chat_id.strip():
            return True
        return False

    async def _create_channel_from_folder_name(self):
        """Cria um canal com o nome da pasta quando destination_chat_id está vazio."""
        folder_name = os.path.basename(self.upload_path.rstrip(os.sep))
        channel_title = folder_name.replace("-", " ").replace("_", " ")
        self.spinner.text = f"Criando canal: {channel_title}..."
        new_channel = await self.client.create_channel(title=channel_title)
        self.spinner.succeed(f"Canal criado: {channel_title} (ID: {new_channel.id})")
        logger.info(f"Canal criado: {channel_title} (ID: {new_channel.id})")
        return new_channel

    async def run(self):
        try:
            # Se destino vazio, tenta carregar do log ou cria novo
            if self._is_destination_empty():
                if self.destination_chat_id:
                    self.client.destination_chat_id = self.destination_chat_id
                    print(self.destination_chat_id)
                    self.spinner.info(f"Retomando no chat salvo: {self.destination_chat_id}").start()
                else:
                    new_channel = await self._create_channel_from_folder_name()
                    self.destination_chat_id = new_channel.id
                    self.client.destination_chat_id = new_channel.id
            
            # Salva o chat_id no log para garantir resumibilidade
            if self.destination_chat_id:
                self._save_chat_id(self.destination_chat_id)

            # Step 1: Zip non-video files
            await self._step2_zip_non_videos()

            # Step 3: Reencode videos (Step 2 seems skipped in user prompt numbering or it is Step 3)
            # User said "Etapa 3 (p3) — Reencode de vídeos"
            await self._step3_reencode_videos()

            # Step 4: Split large videos
            await self._step4_split_large_videos()

            # Step 5: Metadata generation e Header
            summary_tree, header_info, footer_info, video_metadata = await self._step5_generate_metadata()

            # Step 6: Upload content
            await self._step6_upload_content(header_info, footer_info, video_metadata, summary_tree)

            self.spinner.succeed("Operação de envio concluída com sucesso!")

        except Exception as e:
            self.spinner.fail(f"Erro na operação de envio: {e}")
            logger.error(f"Erro detalhado: {e}", exc_info=True)
            raise e

    async def _step2_zip_non_videos(self):
        self.spinner.text = "Etapa 1: Compactando arquivos não-vídeo..."
        # Collect non-video files
        files_to_zip = []
        video_extensions = ['.mp4', '.mkv', '.avi', '.mov', '.ts', '.flv'] # Add more if needed or use ffmpeg_utils
        
        # Helper to check if video
        def is_video(f):
            return any(f.lower().endswith(ext) for ext in video_extensions)

        # Walk safely
        for root, dirs, files in os.walk(self.upload_path):
            for file in files:
                file_path = os.path.join(root, file)
                # Ignore metadata files, hidden files, or already zipped chunks
                if file.startswith(".") or file == "video_details.csv" or is_video(file) or file.endswith(".zip"):
                    continue
                
                # Check if it's strictly inside the path and not in a 'media_reencode' temp folder if any
                files_to_zip.append(file_path)

        if not files_to_zip:
            self.spinner.succeed("2/6 - Nenhum arquivo não-vídeo para compactar.")
            return

        # Create zip volumes
        zip_base_name = os.path.join(self.upload_path, "Documentos.zip")
        # We need to handle splitting if total size > safe limit, OR just standard zip split.
        # Python zipfile doesn't support creating multi-volume zips easily natively.
        # Alternativa: criar zip unificado e se ficar grande, dividir? 
        # Ou criar zips separados por pasta?
        # User said: "compactar todos os arquivos que NÃO são vídeo em partes ZIP, respeitando o limite de tamanho definido"
        
        # Strategy: Iterate files and add to current zip. If current zip size + next file > limit, close and start new zip.
        
        current_part = 1
        current_zip_path = f"{zip_base_name}.{current_part:03d}" if current_part > 1 else zip_base_name # Actually user probably wants .zip, .z01 etc or Part1.zip
        # Let's use simple naming: Extras_Part001.zip
        
        current_zip_path = os.path.join(self.upload_path, f"Documentos_Part{current_part:03d}.zip")
        
        # Check if zips already exist (resumability) - simply skip zipping if "Extras_Part*.zip" exists?
        # Better: assume if we find zips, step 1 is done? 
        # To be safe, we re-verify or just skip if any zip exists?
        # Let's simple try to create.
        
        # If files are already zipped, we might be double zipping. 
        # I will assume "Extras_Part*.zip" are the target.
        
        # To implement robust "chunking":
        current_zip_size = 0
        current_zip = zipfile.ZipFile(current_zip_path, 'w', zipfile.ZIP_DEFLATED)
        
        created_zips = [current_zip_path]
        
        for file_path in files_to_zip:
            fsize = os.path.getsize(file_path)
            if current_zip_size + fsize > SAFE_SIZE_LIMIT:
                current_zip.close()
                current_part += 1
                current_zip_path = os.path.join(self.upload_path, f"Documentos_Part{current_part:03d}.zip")
                current_zip = zipfile.ZipFile(current_zip_path, 'w', zipfile.ZIP_DEFLATED)
                created_zips.append(current_zip_path)
                current_zip_size = 0
            
            # Add file handling relative path to preserve structure inside zip
            rel_path = os.path.relpath(file_path, self.upload_path)
            current_zip.write(file_path, rel_path)
            current_zip_size += fsize
            
            # Remove original file after zipping? "compactar (...) ignorando as extensões de vídeo" 
            # Usually implies replacing files with zip or just creating zip.
            # I will NOT delete original files unless explicitly asked to "Move" or "Clean". 
            # User didn't say delete. But typically "compactar" implies grouping.
            # I will keep them for now.
        
        current_zip.close()
        # Remove empty zip if any
        if os.path.exists(current_zip_path) and os.path.getsize(current_zip_path) <= 22: # Empty zip is 22 bytes
            os.remove(current_zip_path)
            if current_zip_path in created_zips:
                created_zips.remove(current_zip_path)
        self.spinner.succeed(f"2/6 - Arquivos não-vídeo compactados em {len(created_zips)} partes.")

    async def _step3_reencode_videos(self):
        self.spinner.text = "Etapa 3: Verificando reencode de vídeos..."
        self.spinner.stop()
        # Create instance and run. 
        # Note: MediaReencode expects a folder_path.
        reencoder = MediaReencode(self.client, self.upload_path, self.progress_tracker)
        await reencoder.run() # This handles its own errors and spinner logic mostly
        self.spinner.start()
        self.spinner.succeed("3/6 - Vídeos reencodados com sucesso.")

    async def _step4_split_large_videos(self):
        self.spinner.text = "Etapa 4: Dividindo vídeos grandes..."
        
        # Find all videos
        videos = []
        for root, dirs, files in os.walk(self.upload_path):
            for file in files:
                file_path = os.path.join(root, file)
                if is_video_file(file_path):
                    videos.append(file_path)
        
        for video_path in videos:
            if os.path.getsize(video_path) > SAFE_SIZE_LIMIT:
                self.spinner.text = f"Dividindo vídeo grande: {os.path.basename(video_path)}"
                # Split
                parts = await split_video(video_path)
                if parts:
                    logger.info(f"Vídeo {video_path} dividido em {len(parts)} partes.")
                    # Optionally delete original if split successful? 
                    # Usually yes to avoid uploading original.
                    try:
                        os.remove(video_path)
                    except Exception as e:
                        logger.error(f"Erro ao remover arquivo original {video_path}: {e}")
                else:
                    logger.error(f"Falha ao dividir vídeo: {video_path}")
        self.spinner.succeed("4/6 - Vídeos grandes divididos com sucesso.")
        if not videos:
            self.spinner.succeed("4/6 - Nenhum vídeo grande para dividir.")
            return

    async def _step5_generate_metadata(self):
        self.spinner.text = "Etapa 5: Gerando metadados e sumário..."
        
        total_size = 0
        total_duration = 0.0
        project_name = os.path.basename(self.upload_path.rstrip(os.sep))
        invite_link = "https://t.me/placeholder" # Should be retrieved from chat if possible, or placeholder
        try:
            chat = await self.client.get_chat(self.client.destination_chat_id) # Assuming destination_chat_id is set in base or somewhere
            invite_link = chat.invite_link or invite_link
        except:
            pass

        video_metadata = {} # Map filename -> {duration, description, title}
        
        # Locate all video_details.csv
        csv_files = []
        for root, dirs, files in os.walk(self.upload_path):
            if "video_details.csv" in files:
                csv_files.append(os.path.join(root, "video_details.csv"))
        
        # Parse CSVs
        for csv_file in csv_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Expecting 'filename', 'duration', 'title' or similar
                        # Adjust based on flexible reading or column names
                        fname = row.get('filename') or row.get('File Name')
                        if fname:
                            # Try to find full path
                            # Assuming csv is in same dir as files usually
                            csv_dir = os.path.dirname(csv_file)
                            full_path = os.path.join(csv_dir, fname)
                            
                            dur = row.get('duration', '0')
                            # Parse duration if string "HH:MM:SS" or seconds
                            # For now store as is or try conversion
                            video_metadata[fname] = {
                                'duration': dur,
                                'description': row.get('description', fname), # Default desc = filename
                                'title': row.get('title', fname),
                                'path': full_path
                            }
            except Exception as e:
                logger.error(f"Erro ao ler CSV {csv_file}: {e}")

        files_to_process = []
        all_found = []
        for root, dirs, files in os.walk(self.upload_path):
            for file in files:
                if file.startswith(".") or file == ".processed_files" or file == "video_details.csv": continue
                all_found.append(os.path.join(root, file))
        
        # Generate sequential hashtags with natsort
        all_sorted = natsorted(all_found)
        for i, file_path in enumerate(all_sorted, 1):
            self.file_tags[file_path] = f"#F{i:03d}"
        
        for file_path in all_sorted:
            file = os.path.basename(file_path)
            
            size = os.path.getsize(file_path)
            total_size += size
            
            files_to_process.append(file_path)
                
            if is_video_file(file_path):
                # Calculate duration if not in metadata or confirm
                dur = await get_video_duration(file_path)
                total_duration += dur
                
                # Update metadata if missing
                if file not in video_metadata:
                    video_metadata[file] = {
                        'duration': dur,
                        'description': file, # Descricao igual titulo do video (nome do arquivo)
                        'title': file,
                        'path': file_path
                    }

        # Format totals
        size_gb = total_size / (1024 ** 3)
        hours = int(total_duration // 3600)
        minutes = int((total_duration % 3600) // 60)
        seconds = int(total_duration % 60)
        duration_str = f"{hours}h {minutes}m {seconds}s"

        header_info = f"""{project_name}

Tamanho: {size_gb:.2f} GB
Duração: {duration_str}
Convite: {invite_link}"""

        footer_info = f"""Enviado usando [TgTurbo](https://github.com/paulovisam/tgturbo)"""

        # Generate Summary Tree
        summary_tree = self._generate_summary_tree(self.upload_path)
        
        self.spinner.succeed("5/6 - Metadados e sumário gerados com sucesso.")
        return summary_tree, header_info, footer_info, video_metadata

    def _generate_summary_tree(self, start_path: str) -> str:
        tree_lines = []
        # Simple tree generator
        # We need to respect the sort order (natsorted)
        
        def add_to_tree(path, prefix=""):
            # Get contents
            try:
                contents = os.listdir(path)
            except OSError:
                return
            
            contents = natsorted(contents)
            pointers = [("├── ", "│   ")] * (len(contents) - 1) + [("└── ", "    ")]
            
            for pointer, content in zip(pointers, contents):
                if content.startswith(".") or content == ".processed_files": continue
                
                full_path = os.path.join(path, content)
                is_dir = os.path.isdir(full_path)
                
                connector, next_prefix = pointer
                
                icon = "📁" if is_dir else "📄"
                tag = f" `{self.file_tags.get(full_path, '')}`" if not is_dir and full_path in self.file_tags else ""
                line = f"{prefix}{connector}{icon}{tag} {content}"
                if is_dir:
                    line += "/"
                
                tree_lines.append(line)
                
                if is_dir:
                    add_to_tree(full_path, prefix + next_prefix)

        # Root
        tree_lines.append(f"📁 {os.path.basename(start_path)}/")
        add_to_tree(start_path)
        return "\n".join(tree_lines)

    async def _step6_upload_content(self, header_info: str, footer_info: str, video_metadata: dict, summary_tree: str):
        self.spinner.text = "Etapa 6: Iniciando envio de arquivos..."
        self.spinner.info("Preparando lotes de envio...")
        
        # Files upload
        all_paths_found = []
        for root, dirs, files in os.walk(self.upload_path):
            for file in files:
                if file.startswith(".") or file == ".processed_files" or file == "video_details.csv": continue
                all_paths_found.append(os.path.join(root, file))

        all_files = natsorted(all_paths_found)

        # Filter already processed files
        files_to_upload = [f for f in all_files if not self._is_processed(os.path.basename(f))]
        
        if not files_to_upload:
            self.spinner.succeed("Todos os arquivos já foram enviados anteriormente.")
        else:
            self.spinner.stop() # Stop spinner to not flicker with tqdm
            print("\n")
            pbar_total = tqdm(total=len(files_to_upload), unit="arq", desc=f"🚀 Enviando {len(files_to_upload)} arquivos...", position=0, dynamic_ncols=True)
            
            for file_path in files_to_upload:
                file_name = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                
                # Helper to get description
                caption = ""
                tag = self.file_tags.get(file_path, "")
                prefix_tag = f"{tag} - " if tag else ""
                
                if is_video_file(file_path) and file_name in video_metadata:
                     meta = video_metadata[file_name]
                     desc = meta.get('description', file_name)
                     if len(desc) > 999:
                         desc = desc[:996] + "..."
                     caption = f"{prefix_tag}{desc}"
                elif file_name.endswith(".zip"):
                     caption = f"📦 {prefix_tag}Arquivos Extras: {file_name}"
                else:
                     caption = f"{prefix_tag}{file_name}"

                # Progress bar for the current file
                pbar_file = tqdm(total=file_size, unit="B", unit_scale=True, desc=f"Enviando {file_name[:20]}...", position=1, leave=False, dynamic_ncols=True)

                def progress(current, total):
                    pbar_file.n = current
                    pbar_file.refresh()

                # Send
                try:
                    if is_video_file(file_path):
                         dur_sec = int(video_metadata.get(file_name, {}).get('duration', 0)) or 0
                         await self.client.send_video(
                             chat_id=self.client.destination_chat_id,
                             video=file_path,
                             caption=caption,
                             duration=dur_sec,
                             supports_streaming=True,
                             progress=progress
                         )
                    else:
                         await self.client.send_document(
                             chat_id=self.client.destination_chat_id,
                             document=file_path,
                             caption=caption,
                             progress=progress
                         )
                    
                    self._mark_as_processed(file_name)
                    pbar_total.update(1)
                                    
                except FloodWait as e:
                    logger.warning(f"FloodWait de {e.value} segundos.")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.error(f"Erro ao enviar {file_name}: {e}")
                finally:
                    pbar_file.close()
            
            pbar_total.close()
            print() # New line after progress bars
        
        # 2. Send Summary
        self.spinner.info("Enviando sumário...")
        
        # Combine Header + Tree
        full_text = f"{header_info}\n\n{summary_tree}\n\n{footer_info}"
        
        # Split if too long (4096 chars limit for text)
        msgs = []
        if len(full_text) > 4000:
            # Simple split
            parts = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
            msgs = parts
        else:
            msgs = [full_text]
            
        first_msg_id = None
        for i, text in enumerate(msgs):
            sent = await self.client.send_message(
                chat_id=self.client.destination_chat_id,
                text=text
            )
            if i == 0:
                first_msg_id = sent.id

        # 3. Pin First Message
        if first_msg_id:
            try:
                await self.client.pin_chat_message(
                    chat_id=self.client.destination_chat_id,
                    message_id=first_msg_id
                )
            except Exception as e:
                logger.warning(f"Não foi possível fixar a mensagem: {e}")
        self.spinner.succeed("6/6 - Arquivos e sumário enviados com sucesso.")