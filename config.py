from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    QOBUZ_LOGIN = os.getenv("QOBUZ_LOGIN")
    QOBUZ_PASSWORD = os.getenv("QOBUZ_PASSWORD")
    
    # Переменная для AudD.io
    AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")

    # --- ДОБАВИТЬ ЭТИ ДВЕ СТРОКИ ---
    SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
    SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
    
    DOWNLOAD_DIR = Path("/opt/musicBot/Qobuz/Downloads")
    MAX_FILE_SIZE_MB = 2000
    LOG_FILE = Path("logs/bot.log")