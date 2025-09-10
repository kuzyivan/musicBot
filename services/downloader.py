import subprocess
from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_track(self, url: str, quality: str = "6") -> Tuple[Optional[Path], Optional[Path]]:
        try:
            logger.info(f"Запуск qobuz-dl для URL: {url} с качеством: {quality}")
            cmd = [
                str(Config.QOBUZ_DL_PATH),
                "dl", url,
                "--no-db",
                "--quality", quality,
                "--output", str(self.download_dir),
                "--username", os.getenv("QOBUZ_LOGIN"),
                "--password", os.getenv("QOBUZ_PASSWORD")
            ]

            result = subprocess.run(
                cmd,
                cwd=self.download_dir,
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Qobuz-dl stdout: {result.stdout}")
            if result.stderr:
                logger.warning(f"Qobuz-dl stderr: {result.stderr}")

            audio_file, cover_file = self._find_downloaded_files()
            if audio_file:
                logger.info(f"Найден скачанный файл: {audio_file}")
            else:
                logger.warning("Скачанный аудиофайл не найден.")
            
            return audio_file, cover_file
        except subprocess.CalledProcessError as e:
            logger.error(f"Команда qobuz-dl завершилась с ошибкой: {e.stderr}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        audio_file = next(
            (f for f in self.download_dir.glob("**/*.*") if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}),
            None
        )
        cover_file = next(
            (f for f in self.download_dir.glob("**/cover.jpg") if f.is_file()),
            None
        )
        return audio_file, cover_file