from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    DOWNLOAD_DIR = Path("/root/musicBot/Qobuz/Downloads")
    QOBUZ_DL_PATH = Path("/opt/qobuz-env/bin/qobuz-dl")
    MAX_FILE_SIZE_MB = 2000  # 2 GB
    LOG_FILE = Path("logs/bot.log")