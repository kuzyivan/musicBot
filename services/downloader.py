from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
# Импортируем сам модуль
from qobuz_dl.core import QobuzDL

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Инициализируем клиент Qobuz один раз при создании объекта
        self.client = QobuzDL()
        try:
            logger.info("Инициализация клиента Qobuz...")
            self.client.get_tokens()
            self.client.initialize_client(
                Config.QOBUZ_LOGIN,
                Config.QOBUZ_PASSWORD,
                self.client.app_id,
                self.client.secrets
            )
            logger.info("Клиент Qobuz успешно инициализирован.")
        except Exception as e:
            logger.exception("Не удалось инициализировать клиент Qobuz!")
            self.client = None

    async def download_track(self, url: str, quality: str) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.client:
            logger.error("Клиент Qobuz не инициализирован. Скачивание невозможно.")
            return None, None
            
        try:
            # Качество в модуле задается иначе, чем в командной строке.
            # Мы передаем ID качества напрямую. `quality` у вас это "6", "5" и т.д.
            # Эти ID соответствуют тем, что используются в API.
            quality_id = int(quality)
            logger.info(f"Запуск скачивания для URL: {url} с качеством ID: {quality_id}")
            
            # Вместо subprocess используем метод handle_url
            self.client.handle_url(
                url,
                quality=quality_id,
                output_dir=self.download_dir,
                embed_art=True,  # Сразу встраиваем обложку
                no_db=True       # Не используем базу данных для дубликатов
            )

            audio_file, cover_file = self._find_downloaded_files()
            if audio_file:
                logger.info(f"Найден скачанный файл: {audio_file}")
            else:
                logger.warning("Скачанный аудиофайл не найден.")
            
            return audio_file, cover_file
        except Exception as e:
            logger.error(f"Ошибка при скачивании через модуль qobuz-dl: {e}")
            logger.exception("Traceback ошибки:")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        # Поиск файлов остается таким же
        for f in self.download_dir.glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                audio_file = f
                # Обложка уже встроена, но может лежать и рядом
                cover_file = audio_file.parent / "cover.jpg"
                return audio_file, cover_file if cover_file.exists() else None
        return None, None