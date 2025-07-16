import subprocess
from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_track(self, url: str) -> Tuple[Optional[Path], Optional[Path]]:
        try:
            cmd = [
                str(Config.QOBUZ_DL_PATH),
                "dl", url,
                "--no-db",
                "--quality", "6"
            ]

            result = subprocess.run(
                cmd,
                cwd=self.download_dir,
                capture_output=True,
                text=True,
                check=True
            )

            logger.info(f"Qobuz-dl output: {result.stdout}")
            if result.stderr:
                logger.warning(f"Qobuz-dl stderr: {result.stderr}")

            return self._find_downloaded_files()
        except subprocess.CalledProcessError as e:
            logger.error(f"Download failed: {e.stderr}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
    """Поиск скачанных файлов"""
    audio_file = next(
        (f for f in self.download_dir.glob("**/*.*") if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}),
        None
    )
    cover_file = next(
        (f for f in self.download_dir.glob("**/cover.jpg") if f.is_file()),
        None
    )
    return audio_file, cover_file