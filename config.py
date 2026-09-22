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

    QOBUZ_APP_ID = os.getenv("QOBUZ_APP_ID", "798273057")

    QOBUZ_AUTH_TOKEN = os.getenv("QOBUZ_AUTH_TOKEN", "")

    # `or "0"` — защита от пустой переменной: GitHub Actions подставляет
    # несуществующий секрет как пустую строку, и int("") уронил бы бота при старте.

    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID") or "0")

    ALLOWED_USERS: set = {
        int(uid.strip())
        for uid in os.getenv("ALLOWED_USERS", "").split(",")
        if uid.strip().isdigit()
    }

    

    # Переменная для AudD.io

    AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN")



    # --- ДОБАВИТЬ ЭТИ ДВЕ СТРОКИ ---

    SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")

    SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

    

    # --- Apple Music (gamdl) ---

    # cookies.txt в Netscape-формате с cookie media-user-token (.music.apple.com)

    APPLE_MUSIC_COOKIES = Path(os.getenv("APPLE_MUSIC_COOKIES") or BASE_DIR / "cookies.txt")

    # gamdl живёт в отдельном venv: он требует httpx>=0.28, а python-telegram-bot пинит ~=0.25.2

    APPLE_MUSIC_GAMDL = BASE_DIR / "gamdl-venv" / "bin" / "gamdl"

    # Отдельно от DOWNLOAD_DIR: QobuzDownloader чистит свой каталог рекурсивно
    # и при одновременной загрузке снёс бы файл Apple Music.

    APPLE_MUSIC_DOWNLOAD_DIR = BASE_DIR / "AppleMusic" / "Downloads"

    # --- Spotify (метаданные через spotipy, загрузка через Qobuz или yt-dlp) ---

    SPOTIFY_DOWNLOAD_DIR = BASE_DIR / "Spotify" / "Downloads"
    YT_DLP_PATH = BASE_DIR / "venv" / "bin" / "yt-dlp"

    DOWNLOAD_DIR = BASE_DIR / "Qobuz/Downloads"

    MAX_FILE_SIZE_MB = 2000

    LOG_FILE = BASE_DIR / "logs/bot.log"
