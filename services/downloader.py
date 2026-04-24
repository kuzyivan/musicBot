from pathlib import Path
from typing import Optional, Tuple, Callable, Awaitable, Dict
from config import Config
import logging
import sys
import asyncio
import re
import shutil
import httpx

logger = logging.getLogger(__name__)

QOBUZ_API = "https://www.qobuz.com/api.json/0.2"


class QobuzAuthError(Exception):
    pass
QOBUZ_TO_RIP_QUALITY = {27: 4, 7: 3, 6: 2, 5: 1}


class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.rip_path = Path(sys.executable).parent / "rip"
        self._headers = {
            "X-App-Id": Config.QOBUZ_APP_ID,
            "X-User-Auth-Token": Config.QOBUZ_AUTH_TOKEN,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
        }
        logger.info("✅ Сервис загрузки Qobuz (streamrip) инициализирован.")

    async def get_album_info(self, url: str) -> Optional[Dict]:
        album_id = self._extract_id(url)
        if not album_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{QOBUZ_API}/album/get",
                    params={"album_id": album_id, "app_id": Config.QOBUZ_APP_ID},
                    headers=self._headers,
                )
                if r.status_code != 200:
                    logger.warning(f"⚠️ Album API вернул {r.status_code}")
                    return None
                data = r.json()
                tracks = [
                    {"index": i + 1, "title": t["title"], "id": str(t["id"])}
                    for i, t in enumerate(data.get("tracks", {}).get("items", []))
                ]
                if not tracks:
                    return None
                return {
                    "title": data.get("title", "Unknown Album"),
                    "artist": data.get("artist", {}).get("name", "Unknown Artist"),
                    "tracks": tracks[:50],
                }
        except Exception as e:
            logger.error(f"❌ Ошибка при получении информации об альбоме: {e}")
            return None

    async def search_and_download_lucky(
        self,
        artist: str,
        title: str,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
        query = f"{artist} {clean_title}"
        logger.info(f"🔍 Поиск трека на Qobuz: '{query}'")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{QOBUZ_API}/catalog/search",
                    params={"query": query, "type": "tracks", "limit": 1,
                            "app_id": Config.QOBUZ_APP_ID},
                    headers=self._headers,
                )
                if r.status_code != 200:
                    logger.warning(f"⚠️ Поиск вернул {r.status_code}: {r.text[:200]}")
                    return None, None
                items = r.json().get("tracks", {}).get("items", [])
                if not items:
                    logger.warning("⚠️ Треки не найдены")
                    return None, None
                track_id = items[0]["id"]
                track_url = f"https://open.qobuz.com/track/{track_id}"
                logger.info(f"✅ Найден трек ID={track_id}")

            self._clear_download_dir()
            command = [
                str(self.rip_path), "-f", str(self.download_dir),
                "-q", "4", "--no-db", "--no-progress", "url", track_url,
            ]
            return await self._run_rip(command, progress_callback)
        except Exception as e:
            logger.error(f"❌ Ошибка при поиске и скачивании: {e}")
            return None, None

    async def download_track(
        self,
        url: str,
        quality_id: int,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
        track_index: Optional[int] = None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        rip_quality = QOBUZ_TO_RIP_QUALITY.get(quality_id, 3)
        logger.info(f"⬇️ Скачивание: {url} (rip quality={rip_quality})")

        download_url = url
        if track_index is not None and "/album/" in url:
            album_info = await self.get_album_info(url)
            if album_info and len(album_info["tracks"]) >= track_index:
                track_id = album_info["tracks"][track_index - 1]["id"]
                download_url = f"https://open.qobuz.com/track/{track_id}"
                logger.info(f"🎵 Трек №{track_index}: ID={track_id}")

        self._clear_download_dir()
        command = [
            str(self.rip_path), "-f", str(self.download_dir),
            "-q", str(rip_quality), "--no-db", "--no-progress",
            "url", download_url,
        ]
        return await self._run_rip(command, progress_callback)

    def _extract_id(self, url: str) -> Optional[str]:
        m = re.search(r'/(?:album|track)/(\w+)', url)
        return m.group(1) if m else None

    def _clear_download_dir(self):
        for item in self.download_dir.glob("**/*"):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    async def _run_rip(
        self,
        command: list,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        if progress_callback:
            await progress_callback(5.0)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        all_output = []
        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', line_bytes.decode("utf-8", errors="ignore")).strip()
            if line:
                all_output.append(line)
                logger.debug(f"rip: {line}")

        await process.wait()

        if process.returncode != 0:
            output_text = "\n".join(all_output)
            logger.error(f"❌ rip завершился с ошибкой (код {process.returncode}):\n{output_text}")
            if "AuthenticationError" in output_text or "Invalid credentials" in output_text or "authentication" in output_text.lower():
                raise QobuzAuthError("Токен Qobuz истёк или недействителен")
            return None, None

        logger.info("✅ rip завершён. Ищем файл...")
        if progress_callback:
            await progress_callback(100.0)
        return self._find_downloaded_files()

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        for f in self.download_dir.glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                try:
                    f.resolve().relative_to(self.download_dir.resolve())
                except ValueError:
                    logger.warning(f"Попытка обхода каталога! Файл '{f}' вне директории.")
                    continue
                cover_files = list(f.parent.glob("*.jpg")) + list(f.parent.glob("*.png"))
                cover_file = cover_files[0] if cover_files else self._extract_cover(f)
                return f, cover_file if cover_file and cover_file.exists() else None
        return None, None

    def _extract_cover(self, audio_path: Path) -> Optional[Path]:
        try:
            import mutagen
            audio = mutagen.File(audio_path)
            if not audio:
                return None
            pictures = getattr(audio, "pictures", [])
            if not pictures:
                return None
            cover_path = audio_path.parent / "cover.jpg"
            cover_path.write_bytes(pictures[0].data)
            logger.info(f"🖼️ Обложка извлечена из {audio_path.name}")
            return cover_path
        except Exception as e:
            logger.warning(f"⚠️ Не удалось извлечь обложку: {e}")
            return None
