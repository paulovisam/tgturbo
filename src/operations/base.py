###############################################################################
# Classe base para operações (possibilita escalabilidade com novos métodos)
###############################################################################
from pyrogram.client import Client
from src.progress_tracker import ProgressTracker

class BaseOperation:
    def __init__(self, client: Client, progress_tracker: ProgressTracker):
        self.client = client
        self.progress_tracker = progress_tracker