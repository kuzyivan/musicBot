from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()



# Определяем базовую директорию проекта (где находится этот файл)

BASE_DIR = Path(__file__).resolve().parent



class Config:

    BOT_TOKEN = os.getenv("BOT_TOKEN")

    QOBUZ_LOGIN = os.getenv("QOBUZ_LOGIN")

    QOBUZ_PASSWORD = os.getenv("QOBUZ_PASSWORD")

    

    # Переменная для AudD.io

    AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")



    # --- ДОБАВИТЬ ЭТИ ДВЕ СТРОКИ ---

    SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")

    SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

    

    # --- ИСПРАВЛЕНИЕ ПУТИ ---

    # Пути теперь относительные к корню проекта, а не абсолютные

    DOWNLOAD_DIR = BASE_DIR / "Qobuz/Downloads"

    MAX_FILE_SIZE_MB = 2000

    LOG_FILE = BASE_DIR / "logs/bot.log"
