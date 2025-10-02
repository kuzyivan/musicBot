from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
from qobuz_dl.core import QobuzDL

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
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

    async def download_track(self, url: str, quality_id: int) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.client:
            logger.error("Клиент Qobuz не инициализирован. Скачивание невозможно.")
            return None, None
            
        original_dir = Path.cwd()
        try:
            logger.info(f"Запуск скачивания для URL: {url} с качеством ID: {quality_id}")
            self.client.limit_quality = quality_id
            self.client.no_db = True
            
            os.chdir(self.download_dir)
            
            # Убрали embed_art=True, так как будем делать это вручную
            self.client.handle_url(url)

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
        finally:
            os.chdir(original_dir)

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        for f in Path(".").glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                audio_file = self.download_dir / f
                cover_file = self.download_dir / f.parent / "cover.jpg"
                return audio_file, cover_file if cover_file.exists() else None
        return None, None