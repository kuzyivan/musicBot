from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
from qobuz_dl.core import QobuzDL
import subprocess  # <-- Добавляем импорты
import re
import sys

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            self.client = QobuzDL()
            logger.info("Клиент Qobuz успешно инициализирован (используя сохраненную сессию).")
        except Exception as e:
            logger.exception("Не удалось инициализировать клиент Qobuz! Убедитесь, что вы выполнили 'qobuz-dl -r' на сервере.")
            self.client = None

    # --- ПОЛНОСТЬЮ ПЕРЕПИСАННЫЙ МЕТОД ПОИСКА ---
    def search_track(self, artist: str, title: str) -> Optional[str]:
        """Ищет трек по артисту и названию через CLI 'lucky', возвращает URL."""
        query = f"{artist} {title}"
        logger.info(f"Поиск на Qobuz через CLI 'lucky' по запросу: '{query}'")
        
        try:
            # Находим путь к исполняемому файлу qobuz-dl внутри нашего venv
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"

            if not qobuz_dl_path.exists():
                logger.error(f"Не найден исполняемый файл qobuz-dl по пути {qobuz_dl_path}")
                return None

            # Формируем команду
            command = [
                str(qobuz_dl_path),
                "lucky",
                query,
                "--type", "track"
            ]
            
            # Запускаем команду и перехватываем ее вывод
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Команда 'qobuz-dl lucky' завершилась с ошибкой: {result.stderr}")
                return None

            # Ищем ссылку в выводе команды с помощью регулярного выражения
            output = result.stdout
            logger.debug(f"Вывод 'qobuz-dl lucky':\n{output}")
            
            match = re.search(r"(https?://open\.qobuz\.com/track/\d+)", output)
            if match:
                url = match.group(1)
                logger.info(f"Найдена ссылка на трек: {url}")
                return url
            else:
                logger.warning(f"В выводе 'qobuz-dl lucky' не найдена ссылка на трек.")

        except Exception as e:
            logger.error(f"Ошибка при поиске через CLI: {e}")
        
        logger.warning(f"Трек '{query}' не найден на Qobuz.")
        return None


    async def download_track(self, url: str, quality_id: int) -> Tuple[Optional[Path], Optional[Path]]:
        if not self.client:
            logger.error("Клиент Qobuz не инициализирован. Скачивание невозможно.")
            return None, None
            
        original_dir = Path.cwd()
        try:
            logger.info(f"Запуск скачивания для URL: {url} с качеством ID: {quality_id}")
            self.client.limit_quality = quality_id
            self.client.no_db = True
            self.client.embed_art = True
            
            os.chdir(self.download_dir)
            
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