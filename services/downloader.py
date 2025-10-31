from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
import subprocess
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

    def _get_config_path(self) -> str:
        """
        Определяет путь к config.ini, который создается deploy-скриптом.
        Путь: /opt/musicBot/home/.config/qobuz-dl/config.ini
        """
        # Config.DOWNLOAD_DIR = /opt/musicBot/Qobuz/Downloads
        # APP_DIR = /opt/musicBot
        APP_DIR = Config.DOWNLOAD_DIR.parent.parent
        return str(APP_DIR / "home" / ".config" / "qobuz-dl" / "config.ini")

    def search_and_download_lucky(self, artist: str, title: str) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Ищет трек через 'lucky' и, т.к. он сразу скачивает, 
        находит и возвращает путь к скачанному файлу.
        """
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        
        # Санитизация (экранирование) для защиты от Command Injection
        safe_artist = shlex.quote(artist)
        safe_title = shlex.quote(clean_title)
        query = f"{safe_artist} {safe_title}"

        logger.info(f"🔍 Поиск и скачивание на Qobuz через 'lucky': '{query}'")

        # Очищаем папку перед скачиванием
        for item in self.download_dir.glob("**/*"):
            if item.is_file(): item.unlink()
            elif item.is_dir(): shutil.rmtree(item)

        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            config_path = self._get_config_path()

            command = [
                str(qobuz_dl_path), "lucky", query, 
                "--type", "track", "--no-db", "-d", str(self.download_dir),
                "--config-path", config_path  # <-- ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ
            ]
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
        """Скачивает трек по URL через CLI 'dl'."""
        logger.info(f"⬇️ Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            config_path = self._get_config_path()

            for item in self.download_dir.glob("**/*"):
                if item.is_file(): item.unlink()
                elif item.is_dir(): shutil.rmtree(item)

            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art", "--no-db",
                "-d", str(self.download_dir),
                "--config-path", config_path  # <-- ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ
            ]
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
                # --- ПРОВЕРКА ОТ PATH TRAVERSAL ---
                try:
                    f.resolve().relative_to(self.download_dir.resolve())
                except ValueError:
                    logger.warning(
                        f"Попытка обхода каталога! Файл '{f}' вне рабочей директории. Пропускаем."
                    )
                    continue
                # --- КОНЕЦ ПРОВЕРКИ ---

                cover_file = f.parent / "cover.jpg"
                return f, cover_file if cover_file.exists() else None
        return None, None