from pathlib import Path
from typing import Optional, Tuple
from config import Config
# --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
from savify import Savify
from savify.types import Format, Quality
from savify.utils import PathHolder
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---
import logging
import shutil
import asyncio

logger = logging.getLogger(__name__)

class SavifyDownloader:
    def __init__(self):
        # Создадим отдельную временную папку для скачиваний Savify
        self.download_dir = Config.DOWNLOAD_DIR / "savify_temp"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        api_creds = (Config.SPOTIPY_CLIENT_ID, Config.SPOTIPY_CLIENT_SECRET)
        if not all(api_creds):
            logger.error("!!! Savify не будет работать без SPOTIPY_CLIENT_ID и SPOTIPY_CLIENT_SECRET в .env !!!")
            api_creds = None

        # Укажем Savify качать все в нашу папку, НЕ создавая подпапки
        # Теперь `PathHolder` будет найден
        path_holder = PathHolder(downloads_path=self.download_dir)
        
        self.savify = Savify(
            api_credentials=api_creds,
            quality=Quality.BEST,
            download_format=Format.MP3, # Savify лучше всего работает с MP3 для метаданных
            path_holder=path_holder,
            group=None # Отключаем группировку по %artist%/%album%
        )
        logger.info("✅ Сервис загрузки Savify (Spotify) инициализирован.")

    async def download_track(self, url: str) -> Tuple[Optional[Path], Optional[Path]]:
        """Скачивает трек по URL."""
        logger.info(f"⬇️ Запуск скачивания Savify для URL: {url}")
        
        # Очищаем временную папку перед новым скачиванием
        self._clear_temp_dir()

        try:
            # Savify.download() - это блокирующая I/O операция.
            # В асинхронном коде ее нужно запускать в executor'е,
            # чтобы не блокировать весь event-loop.
            loop = asyncio.get_running_loop()
            # Запускаем синхронную функцию в отдельном потоке
            await loop.run_in_executor(None, self.savify.download, url)
            
            logger.info("✅ Скачивание Savify завершено. Поиск файлов...")
            return self._find_downloaded_files()
            
        except Exception as e:
            logger.error(f"❌ Ошибка при скачивании через Savify: {e}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Находит первый скачанный MP3 и его обложку в папке."""
        for f in self.download_dir.glob("**/*.mp3"):
            if f.is_file():
                # Savify (через youtube-dl) может скачать обложку
                cover_file = f.with_suffix(".jpg")
                if not cover_file.exists():
                     cover_file = f.with_suffix(".png") # Пробуем .png
                
                return f, cover_file if cover_file.exists() else None
        return None, None # Не найдено

    def _clear_temp_dir(self):
        """Очищает временную директорию Savify."""
        for item in self.download_dir.glob("**/*"):
            if item.is_file():
                try:
                    item.unlink()
                except OSError as e:
                    logger.warning(f"Не удалось удалить {item}: {e}")
            elif item.is_dir():
                try:
                    shutil.rmtree(item)
                except OSError as e:
                    logger.warning(f"Не удалось удалить директорию {item}: {e}")