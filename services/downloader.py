from pathlib import Path
from typing import Optional, Tuple, Callable, Awaitable, List, Dict
from config import Config
import logging
import os
import asyncio
import re
import sys
import shutil
import shlex
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.info("✅ Сервис загрузки Qobuz (CLI) инициализирован.")

    async def get_album_info(self, url: str) -> Optional[Dict]:
        """Парсит страницу альбома и возвращает информацию и список треков."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code != 200:
                    return None
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Парсим название альбома и артиста
                album_title = soup.find('h1', class_='album-meta__title')
                artist_name = soup.find('span', class_='album-meta__artist')
                
                title = album_title.text.strip() if album_title else "Unknown Album"
                artist = artist_name.text.strip() if artist_name else "Unknown Artist"
                
                # Парсим треки
                tracks = []
                track_elements = soup.find_all('div', class_='track-item')
                
                for i, track in enumerate(track_elements, 1):
                    # Ищем название трека внутри элемента
                    name_elem = track.find('div', class_='track-item__title')
                    if name_elem:
                        tracks.append({
                            'index': i,
                            'title': name_elem.text.strip()
                        })
                
                # Если через классы не нашлось, попробуем другой способ (Qobuz меняет верстку)
                if not tracks:
                    # Поиск всех элементов, похожих на названия треков
                    # В новой верстке Qobuz часто используются другие классы
                    possible_tracks = soup.select('.tracklist__item-title') or soup.select('.track-name')
                    for i, track in enumerate(possible_tracks, 1):
                        tracks.append({
                            'index': i,
                            'title': track.text.strip()
                        })

                return {
                    'title': title,
                    'artist': artist,
                    'tracks': tracks[:50] # Ограничим 50 треками для кнопок
                }
        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге страницы альбома: {e}")
            return None

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
        
        self._clear_download_dir()
            
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
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        track_index: Optional[int] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        logger.info(f"⬇️ Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"
            
            self._clear_download_dir()
            
            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art", "--no-db",
                "-d", str(self.download_dir)
            ]
            
            # Если указан конкретный трек в альбоме
            if track_index is not None:
                command.extend(["--select", str(track_index)])
            
            return await self._run_qobuz_dl(command, progress_callback)
        
        except Exception as e:
            logger.error(f"❌ Ошибка при скачивании через CLI: {e}")
            return None, None

    def _clear_download_dir(self):
        for item in self.download_dir.glob("**/*"):
            if item.is_file(): item.unlink()
            elif item.is_dir(): shutil.rmtree(item)

    async def _run_qobuz_dl(
        self, 
        command: list, 
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """Запускает qobuz-dl и парсит прогресс."""
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        last_percent = -1.0
        buffer = ""
        
        while True:
            char_bytes = await process.stdout.read(1)
            if not char_bytes:
                break
            
            char = char_bytes.decode('utf-8', errors='ignore')
            if char in ['\r', '\n']:
                line = buffer.strip()
                match = re.search(r'(\d+(\.\d+)?)%', line)
                if match and progress_callback:
                    try:
                        percent = float(match.group(1))
                        if percent - last_percent >= 2.0 or percent >= 99.0 or percent < last_percent:
                            await progress_callback(percent)
                            last_percent = percent
                    except ValueError:
                        pass
                buffer = ""
            else:
                buffer += char

        await process.wait()
        
        if process.returncode != 0:
            logger.error(f"❌ Команда qobuz-dl завершилась с ошибкой (код {process.returncode})")
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
                if not cover_file.exists():
                    cover_files = list(f.parent.glob("*.jpg")) + list(f.parent.glob("*.png"))
                    cover_file = cover_files[0] if cover_files else None
                else:
                    cover_file = cover_file
                    
                return f, cover_file if cover_file and cover_file.exists() else None
        return None, None

