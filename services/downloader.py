from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
import subprocess
import re
import sys
import shutil

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Сервис загрузки Qobuz (CLI) инициализирован.")

    def search_track(self, artist: str, title: str) -> Optional[str]:
        # ... (этот метод остается без изменений) ...
        query = f"{artist} {title}"
        logger.info(f"Поиск на Qobuz через CLI 'lucky' по запросу: '{query}'")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"

            command = [str(qobuz_dl_path), "lucky", query, "--type", "track"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            
            # Добавляем подробное логирование
            if result.stdout:
                logger.info(f"Вывод 'qobuz-dl lucky' (stdout):\n{result.stdout}")
            if result.stderr:
                logger.warning(f"Вывод 'qobuz-dl lucky' (stderr):\n{result.stderr}")

            if "Invalid credentials" in result.stderr:
                logger.error("Ошибка аутентификации Qobuz. Пожалуйста, выполните 'qobuz-dl -r' на сервере.")
                return None
            if result.returncode != 0:
                logger.error(f"Команда 'qobuz-dl lucky' завершилась с кодом {result.returncode}.")
                return None

            match = re.search(r"(https?://open\.qobuz\.com/track/\d+)", result.stdout)
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
        logger.info(f"Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"

            for item in self.download_dir.glob("**/*"):
                if item.is_file(): item.unlink()
                elif item.is_dir(): shutil.rmtree(item)

            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art",
                "-d", str(self.download_dir)
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)

            # --- ИЗМЕНЕНИЕ ЗДЕСЬ: ДОБАВЛЯЕМ ПОДРОБНОЕ ЛОГИРОВАНИЕ ---
            if result.stdout:
                logger.info(f"Вывод 'qobuz-dl dl' (stdout):\n{result.stdout}")
            if result.stderr:
                logger.warning(f"Вывод 'qobuz-dl dl' (stderr):\n{result.stderr}")
            # ---------------------------------------------------------

            if "Invalid credentials" in result.stderr:
                logger.error("Ошибка аутентификации Qobuz. Пожалуйста, выполните 'qobuz-dl -r' на сервере.")
                return None, None
            if result.returncode != 0:
                logger.error(f"Команда 'qobuz-dl dl' завершилась с кодом {result.returncode}.")
                return None, None
            
            logger.info("Скачивание через CLI завершено. Поиск файлов...")
            return self._find_downloaded_files()
            
        except Exception as e:
            logger.error(f"Ошибка при скачивании через CLI: {e}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        for f in self.download_dir.glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                return f, f.parent / "cover.jpg"
        return None, None