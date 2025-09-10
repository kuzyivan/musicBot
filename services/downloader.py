from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os  # <-- Добавляем импорт 'os'

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

    async def download_track(self, url: str) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.client:
            logger.error("Клиент Qobuz не инициализирован. Скачивание невозможно.")
            return None, None
            
        # --- ИЗМЕНЕНИЯ ЗДЕСЬ ---
        original_dir = Path.cwd()  # Запоминаем текущую директорию
        try:
            logger.info(f"Запуск скачивания для URL: {url}")
            os.chdir(self.download_dir)  # Переходим в папку для скачивания
            
            # Вызываем функцию handle_url ТОЛЬКО со ссылкой, как в документации
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
            os.chdir(original_dir)  # Возвращаемся в исходную директорию в любом случае

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        # Эта функция теперь будет искать файлы в self.download_dir, куда мы перешли
        for f in Path(".").glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                # Возвращаем абсолютный путь к файлу
                audio_file = self.download_dir / f
                cover_file = self.download_dir / f.parent / "cover.jpg"
                return audio_file, cover_file if cover_file.exists() else None
        return None, None