from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
import subprocess  # <-- Используем subprocess
import re
import sys
import shutil
import shlex

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.info("✅ Сервис загрузки Qobuz (CLI) инициализирован.")

    def search_and_download_lucky(self, artist: str, title: str) -> Tuple[Optional[Path], Optional[Path]]:
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        safe_artist = shlex.quote(artist)
        safe_title = shlex.quote(clean_title)
        query = f"{safe_artist} {safe_title}"
        logger.info(f"🔍 Поиск и скачивание на Qobuz через 'lucky': '{query}'")
        for item in self.download_dir.glob("**/*"):
            if item.is_file(): item.unlink()
            elif item.is_dir(): shutil.rmtree(item)
        try:
            # Ищем qobuz-dl внутри venv, запущенного systemd
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            command = [
                str(qobuz_dl_path), "lucky", query, 
                "--type", "track", "--no-db", "-d", str(self.download_dir)
            ]

            # Выполняем как команду
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                logger.error(f"❌ Команда 'qobuz-dl lucky' завершилась с ошибкой: {result.stderr}")
                return None, None

            logger.info("✅ Команда 'lucky' выполнена. Ищем результат...")
            return self._find_downloaded_files()

        except Exception as e:
            logger.error(f"❌ Ошибка при поиске и скачивании через 'lucky': {e}")
            return None, None

    async def download_track(self, url: str, quality_id: int) -> Tuple[Optional[Path], Optional[Path]]:
        logger.info(f"⬇️ Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            # Ищем qobuz-dl внутри venv, запущенного systemd
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"

            # Очистка папки перед скачиванием
            for item in self.download_dir.glob("**/*"):
                if item.is_file(): item.unlink()
                elif item.is_dir(): shutil.rmtree(item)

            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art", "--no-db",
                "-d", str(self.download_dir)
            ]

            # Выполняем как команду
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)

            if result.returncode != 0:
                logger.error(f"❌ Команда 'qobuz-dl dl' завершилась с ошибкой: {result.stderr}")
                return None, None

            logger.info("✅ Скачивание через CLI завершено. Поиск файлов...")
            return self._find_downloaded_files()

        except Exception as e:
            logger.error(f"❌ Ошибка при скачивании через CLI: {e}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        for f in self.download_dir.glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                try:
                    f.resolve().relative_to(self.download_dir.resolve())
                except ValueError:
                    logger.warning(
                        f"Попытка обхода каталога! Файл '{f}' вне рабочей директории. Пропускаем."
                    )
                    continue
                # Исправляем путь к обложке
                cover_file = f.parent / "cover.jpg"
                return f, cover_file if cover_file.exists() else None
        return None, None