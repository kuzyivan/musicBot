from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DOWNLOAD_DIR = Path("/root/musicBot/Qobuz/Downloads")
    # --- ИЗМЕНЕННАЯ СТРОКА ---
    QOBUZ_DL_PATH = Path("/root/MusicBot/venv/bin/qobuz-dl")
    MAX_FILE_SIZE_MB = 2000
    LOG_FILE = Path("logs/bot.log")