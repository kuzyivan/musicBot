from pathlib import Path
from typing import Optional, Tuple, Callable, Awaitable
from config import Config
import logging
import os
import asyncio
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

    async def search_and_download_lucky(
        self, 
        artist: str, 
        title: str, 
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        safe_artist = shlex.quote(artist)
        safe_title = shlex.quote(clean_title)
        query = f"{safe_artist} {safe_title}"
        logger.info(f"🔍 Поиск и скачивание на Qobuz через 'lucky': '{query}'")
        
        for item in self.download_dir.glob("**/*"):
            if item.is_file(): item.unlink()
            elif item.is_dir(): shutil.rmtree(item)
            
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            
            command = [
                str(qobuz_dl_path), "lucky", query, 
                "--type", "track", "--no-db", "-d", str(self.download_dir)
            ]
            
            return await self._run_qobuz_dl(command, progress_callback)
        
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске и скачивании через 'lucky': {e}")
            return None, None

    async def download_track(
        self, 
        url: str, 
        quality_id: int, 
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        logger.info(f"⬇️ Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            
            for item in self.download_dir.glob("**/*"):
                if item.is_file(): item.unlink()
                elif item.is_dir(): shutil.rmtree(item)
            
            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art", "--no-db",
                "-d", str(self.download_dir)
            ]
            
            return await self._run_qobuz_dl(command, progress_callback)
        
        except Exception as e:
            logger.error(f"❌ Ошибка при скачивании через CLI: {e}")
            return None, None

    async def _run_qobuz_dl(
        self, 
        command: list, 
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """Запускает qobuz-dl и парсит прогресс."""
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        last_percent = -1.0
        
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            
            line = line_bytes.decode('utf-8', errors='ignore').strip()
            
            # Парсинг процентов: ищем что-то вроде [45.2%]
            match = re.search(r'\[(\d+\.?\d*)%\]', line)
            if match and progress_callback:
                percent = float(match.group(1))
                # Обновляем только если процент изменился существенно (на 1% или более)
                if percent - last_percent >= 5.0 or percent >= 99.0:
                    await progress_callback(percent)
                    last_percent = percent

        await process.wait()
        
        if process.returncode != 0:
            stderr_data = await process.stderr.read()
            logger.error(f"❌ Команда qobuz-dl завершилась с ошибкой: {stderr_data.decode()}")
            return None, None
            
        logger.info("✅ Команда выполнена. Ищем результат...")
        return self._find_downloaded_files()

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
                cover_file = f.parent / "cover.jpg"
                return f, cover_file if cover_file.exists() else None
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