from pathlib import Path
from typing import Optional
import os
import logging
import mutagen

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

    @staticmethod
    def get_audio_quality(file_path: Path) -> Optional[str]:
        """
        Анализирует аудиофайл и возвращает строку с его качеством.
        Например: '24-bit / 192.0 kHz'
        """
        try:
            audio = mutagen.File(file_path)
            if not audio:
                return None
            
            bit_depth = getattr(audio.info, 'bits_per_sample', None)
            sample_rate = audio.info.sample_rate

            if not bit_depth:
                # Для MP3 и некоторых других форматов нет bits_per_sample,
                # можно использовать bitrate в качестве альтернативы.
                bitrate = getattr(audio.info, 'bitrate', 0)
                if bitrate > 0:
                    return f"MP3 / {bitrate // 1000} kbps"
                return None

            sample_rate_khz = sample_rate / 1000
            # Убираем .0 для целых чисел, например 44.1, но 96
            if sample_rate_khz.is_integer():
                sample_rate_str = str(int(sample_rate_khz))
            else:
                sample_rate_str = str(sample_rate_khz)

            return f"{bit_depth}-bit / {sample_rate_str} kHz"
            
        except Exception as e:
            logger.error(f"Не удалось прочитать метаданные из файла {file_path}: {e}")
            return None

    @staticmethod
    def format_progress_bar(percent: float, length: int = 10) -> str:
        """Форматирует текстовый прогресс-бар: [████░░░░░░] 40%"""
        filled_length = int(length * percent // 100)
        bar = '█' * filled_length + '░' * (length - filled_length)
        return f"[{bar}] {percent:.1f}%"
