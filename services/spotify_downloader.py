"""
Загрузка по ссылке Spotify.

Spotify не отдаёт аудио для скачивания, поэтому ссылка используется как
источник метаданных: по артисту и названию трек ищется на Qobuz (Hi-Res),
а если там его нет — берётся с YouTube через yt-dlp.

Раньше это делал savify 2.3.4, но он сломан дважды: не получал Logger
(падал на первом же self.logger.info ещё до скачивания) и работал через
youtube_dl 2021 года, который YouTube давно не понимает.
"""
from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import asyncio
import re
import shutil

logger = logging.getLogger(__name__)

YDL_TIMEOUT = 300  # сек

# Ссылки бывают с локалью: open.spotify.com/intl-ru/track/...
_SPOTIFY_URL_RE = re.compile(
    r"(?:https?://)?(?:open\.)?spotify\.com/(?:intl-[a-z]{2}/)?"
    r"(?P<kind>track|album|playlist|artist|episode|show)/(?P<id>[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_SPOTIFY_URI_RE = re.compile(r"spotify:(?P<kind>track|album|playlist|artist|episode|show):(?P<id>[A-Za-z0-9]+)", re.IGNORECASE)


class SpotifyError(Exception):
    """Ошибка Spotify с готовым текстом для пользователя."""

    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


def parse_spotify_url(url: str) -> Optional[dict]:
    """Разбирает ссылку или URI Spotify. Возвращает {'kind', 'id'} или None."""
    text = (url or "").strip()
    for pattern in (_SPOTIFY_URL_RE, _SPOTIFY_URI_RE):
        m = pattern.search(text)
        if m:
            return {"kind": m.group("kind").lower(), "id": m.group("id")}
    return None


class SpotifyDownloader:
    def __init__(self):
        self.download_dir = Config.SPOTIFY_DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.ydl_path = Path(Config.YT_DLP_PATH)
        self._spotify = None
        # Откуда реально пришёл файл: Spotify аудио не отдаёт, поэтому это
        # всегда другой сервис — и подпись должна называть его честно.
        self.last_source: Optional[str] = None

        if not all((Config.SPOTIPY_CLIENT_ID, Config.SPOTIPY_CLIENT_SECRET)):
            logger.error("!!! Spotify не будет работать без SPOTIPY_CLIENT_ID и SPOTIPY_CLIENT_SECRET !!!")

        logger.info("✅ Сервис загрузки Spotify (spotipy + Qobuz/yt-dlp) инициализирован.")

    # --- метаданные ---

    def _client(self):
        if self._spotify is None:
            import spotipy
            from spotipy.cache_handler import MemoryCacheHandler
            from spotipy.oauth2 import SpotifyClientCredentials

            self._spotify = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=Config.SPOTIPY_CLIENT_ID,
                    client_secret=Config.SPOTIPY_CLIENT_SECRET,
                    # Без этого spotipy пишет токен в файл .cache прямо в каталоге
                    # запуска, откуда он попадает в git — держим токен только в памяти.
                    cache_handler=MemoryCacheHandler(),
                )
            )
        return self._spotify

    def _get_track_metadata(self, track_id: str) -> dict:
        try:
            track = self._client().track(track_id)
        except Exception as e:
            logger.error(f"❌ Spotify: не удалось получить метаданные трека {track_id}: {e}")
            raise SpotifyError(
                "❌ Spotify: не удалось получить данные трека.\n"
                "Проверьте SPOTIPY_CLIENT_ID и SPOTIPY_CLIENT_SECRET в .env."
            )

        if not track or not track.get("name"):
            raise SpotifyError("❌ Spotify: трек не найден — возможно, ссылка устарела.")

        images = (track.get("album") or {}).get("images") or []
        return {
            "title": track["name"],
            "artist": ", ".join(a["name"] for a in track.get("artists", [])),
            "album": (track.get("album") or {}).get("name", ""),
            "year": ((track.get("album") or {}).get("release_date") or "")[:4],
            "cover_url": images[0]["url"] if images else None,
        }

    # --- альбомы ---

    def get_album_info(self, url: str) -> Optional[dict]:
        """Список треков альбома — для инлайн-клавиатуры выбора."""
        parsed = parse_spotify_url(url)
        if not parsed or parsed["kind"] != "album":
            return None

        try:
            client = self._client()
            album = client.album(parsed["id"])
            if not album:
                return None

            page = album.get("tracks") or {}
            items = list(page.get("items") or [])
            # Spotify отдаёт по 50 треков на страницу
            while page.get("next"):
                page = client.next(page)
                items.extend(page.get("items") or [])

            tracks = []
            for item in items:
                if not item:  # трек недоступен в регионе аккаунта
                    continue
                tracks.append(
                    {"index": len(tracks) + 1, "title": item["name"], "id": item["id"]}
                )

            if not tracks:
                return None

            images = album.get("images") or []
            return {
                "title": album["name"],
                "artist": ", ".join(a["name"] for a in album.get("artists", [])),
                # ограничение как у Qobuz: клавиатура не должна быть бесконечной
                "tracks": tracks[:50],
                "cover_url": images[0]["url"] if images else None,
            }
        except Exception as e:
            logger.error(f"❌ Spotify: не удалось получить альбом: {e}")
            return None

    # --- загрузка ---

    async def download_track_by_id(self, track_id: str) -> Tuple[Optional[Path], Optional[Path]]:
        """Скачивает трек по его Spotify ID."""
        meta = self._get_track_metadata(track_id)
        logger.info(f"🎧 Spotify: {meta['artist']} — {meta['title']}")
        self._clear_temp_dir()

        # Источники по убыванию качества: Hi-Res → AAC 256 → YouTube-рип
        audio_file, cover_file = await self._download_from_qobuz(meta)
        if not audio_file:
            logger.info("⚠️ Spotify: на Qobuz не найдено, пробую Apple Music")
            audio_file, cover_file = await self._download_from_apple(meta)
        if not audio_file:
            logger.info("⚠️ Spotify: на Apple Music не найдено, беру с YouTube")
            audio_file, cover_file = await self._download_from_youtube(meta)

        if not audio_file:
            return None, None

        # Обложка от источника качественнее арта Spotify (Apple отдаёт 1200px
        # против 640px), поэтому берём её, а к Spotify обращаемся только если
        # источник своей не дал — как YouTube.
        if not cover_file or not cover_file.exists():
            cover_file = await self._save_cover(meta.get("cover_url"), audio_file)

        return audio_file, cover_file

    async def download_track(
        self, url: str, track_index: Optional[int] = None
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Скачивает трек по ссылке Spotify.

        Ссылка на альбом тоже принимается: с track_index (нумерация с 1) берётся
        конкретный трек, без него — первый (весь альбом качает вызывающая сторона,
        чтобы отправлять файлы по мере готовности).
        """
        parsed = parse_spotify_url(url)
        if not parsed:
            raise SpotifyError("❌ Spotify: не удалось разобрать ссылку.")

        if parsed["kind"] == "track":
            track_id = parsed["id"]

        elif parsed["kind"] == "album":
            info = self.get_album_info(url)
            if not info:
                raise SpotifyError("❌ Spotify: не удалось получить список треков альбома.")
            index = track_index or 1
            if not 1 <= index <= len(info["tracks"]):
                raise SpotifyError(f"❌ Spotify: в альбоме нет трека №{index}.")
            track_id = info["tracks"][index - 1]["id"]

        else:
            raise SpotifyError(
                f"🍏 Spotify: ссылки типа «{parsed['kind']}» не поддерживаются.\n\n"
                "Пришлите ссылку на трек или альбом."
            )

        return await self.download_track_by_id(track_id)

    async def _download_from_qobuz(self, meta: dict) -> Tuple[Optional[Path], Optional[Path]]:
        """Hi-Res с Qobuz по метаданным Spotify."""
        from services.downloader import QobuzDownloader, QobuzAuthError

        try:
            downloader = QobuzDownloader()
            audio_file, cover_file = await downloader.search_and_download_lucky(
                meta["artist"], meta["title"]
            )
            if audio_file:
                logger.info(f"✅ Spotify→Qobuz: получен {audio_file.name}")
                self.last_source = "Qobuz"
                return audio_file, cover_file
            return None, None
        except QobuzAuthError:
            logger.warning("⚠️ Spotify: токен Qobuz недействителен, откат на Apple")
            return None, None
        except Exception as e:
            logger.warning(f"⚠️ Spotify: Qobuz недоступен ({e}), откат на Apple")
            return None, None

    async def _download_from_apple(self, meta: dict) -> Tuple[Optional[Path], Optional[Path]]:
        """AAC 256 kbps из Apple Music по метаданным Spotify."""
        from services.apple_music_downloader import AppleMusicDownloader, AppleMusicError

        try:
            downloader = AppleMusicDownloader()
            if not downloader.is_configured():
                logger.info("ℹ️ Spotify: Apple Music пропущен — не настроены cookies")
                return None, None

            audio_file, cover_file = await downloader.search_and_download_lucky(
                meta["artist"], meta["title"]
            )
            if audio_file:
                logger.info(f"✅ Spotify→Apple Music: получен {audio_file.name}")
                self.last_source = "Apple Music"
                return audio_file, cover_file
            return None, None
        except AppleMusicError as e:
            # Нет подписки, протухшие cookies, трек вне региона — не повод
            # падать, просто идём дальше по цепочке
            first_line = e.user_message.splitlines()[0]
            logger.info(f"ℹ️ Spotify: Apple Music недоступен — {first_line}")
            return None, None
        except Exception as e:
            logger.warning(f"⚠️ Spotify: Apple Music ошибка ({e}), откат на YouTube")
            return None, None

    async def _download_from_youtube(self, meta: dict) -> Tuple[Optional[Path], Optional[Path]]:
        """Откат: поиск на YouTube и извлечение аудио в MP3."""
        if not self.ydl_path.exists():
            logger.error(f"❌ Spotify: yt-dlp не найден по пути {self.ydl_path}")
            return None, None

        query = f"ytsearch1:{meta['artist']} - {meta['title']} audio"
        command = [
            str(self.ydl_path),
            "--no-warnings",
            "--no-playlist",
            "-x", "--audio-format", "mp3", "--audio-quality", "0",
            "-o", str(self.download_dir / "%(title)s.%(ext)s"),
            query,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=YDL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Spotify: yt-dlp превысил таймаут {YDL_TIMEOUT}s")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            return None, None
        except Exception as e:
            logger.error(f"❌ Spotify: ошибка запуска yt-dlp: {e}")
            return None, None

        output = stdout.decode("utf-8", errors="ignore")
        if process.returncode != 0:
            logger.error(f"❌ Spotify: yt-dlp завершился с кодом {process.returncode}:\n{output[-1500:]}")

        audio_file = self._find_audio_file()
        if audio_file:
            self._write_tags(audio_file, meta)
            logger.info(f"✅ Spotify→YouTube: получен {audio_file.name}")
            self.last_source = "YouTube"
        # Обложки у YouTube нет — её подставит _save_cover из арта Spotify
        return audio_file, None

    # --- вспомогательное ---

    @staticmethod
    def _write_tags(audio_file: Path, meta: dict):
        """
        Проставляет теги Spotify в скачанный с YouTube файл: иначе подпись
        и имя файла берутся из названия видео, которое часто содержит мусор.
        """
        try:
            import mutagen
            from mutagen.easyid3 import EasyID3

            audio = mutagen.File(audio_file, easy=True)
            if audio is None:
                return
            for key, value in (
                ("title", meta.get("title")),
                ("artist", meta.get("artist")),
                ("album", meta.get("album")),
                ("date", meta.get("year")),
            ):
                if value:
                    audio[key] = value
            audio.save()
            logger.info("🏷️ Spotify: теги проставлены из метаданных Spotify")
        except Exception as e:
            logger.warning(f"⚠️ Spotify: не удалось записать теги: {e}")

    async def _save_cover(self, cover_url: Optional[str], audio_file: Path) -> Optional[Path]:
        """Скачивает обложку альбома Spotify (она качественнее кадра с YouTube)."""
        if not cover_url:
            return None
        cover_path = audio_file.with_name("cover.jpg")
        try:
            import httpx

            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(cover_url)
                if response.status_code == 200:
                    cover_path.write_bytes(response.content)
                    return cover_path
        except Exception as e:
            logger.warning(f"⚠️ Spotify: не удалось скачать обложку: {e}")
        return None

    def _find_audio_file(self) -> Optional[Path]:
        files = [f for f in self.download_dir.glob("**/*.mp3") if f.is_file()]
        if not files:
            return None
        return max(files, key=lambda f: f.stat().st_mtime)

    def _clear_temp_dir(self):
        for item in self.download_dir.glob("*"):
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except OSError as e:
                logger.warning(f"⚠️ Не удалось удалить {item}: {e}")
