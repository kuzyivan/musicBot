from pathlib import Path
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

class FileManager:
    @staticmethod
    def safe_remove(file_path: Optional[Path]):
        if file_path and file_path.exists():
            try:
                os.unlink(file_path)
                logger.info(f"Удалён файл: {file_path}")
            except OSError as e:
                logger.warning(f"Не удалось удалить файл {file_path}: {e}")

    @staticmethod
    def get_file_size_mb(file_path: Path) -> float:
        return file_path.stat().st_size / (1024 * 1024)