from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    # Добавьте эти переменные
    QOBUZ_LOGIN = os.getenv("QOBUZ_LOGIN")
    QOBUZ_PASSWORD = os.getenv("QOBUZ_PASSWORD")
    
    DOWNLOAD_DIR = Path("/root/musicBot/Qobuz/Downloads")
    MAX_FILE_SIZE_MB = 2000
    LOG_FILE = Path("logs/bot.log")