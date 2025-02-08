###############################################################################
# Classe para persistência do progresso (para retomar de onde parou)
###############################################################################

import json, os
from src.log import logger

class ProgressTracker:
    def __init__(self, filename: str = "progress.json"):
        self.filename = filename
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao ler arquivo de progresso: {e}")
                self.data = {}
        else:
            self.data = {}

    def _get_key(self, op: str, chat_id: int, dest_chat_id: int = None) -> str:
        if dest_chat_id:
            return f"{op}_{chat_id}_{dest_chat_id}"
        return f"{op}_{chat_id}"

    def get_last_message_id(self, op: str, chat_id: int, dest_chat_id: int = None) -> int:
        key = self._get_key(op, chat_id, dest_chat_id)
        return self.data.get(key, 0)

    def update(self, op: str, chat_id: int, dest_chat_id: int, message_id: int):
        key = self._get_key(op, chat_id, dest_chat_id)
        self.data[key] = message_id
        self._save()

    def _save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"Erro ao salvar progresso: {e}")
