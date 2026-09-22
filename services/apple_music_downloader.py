from pathlib import Path
from typing import Optional, Tuple, Callable, Awaitable, List
from config import Config
import logging
import asyncio
import re
import shutil
import mutagen

logger = logging.getLogger(__name__)

GAMDL_TIMEOUT = 600  # сек

# Типы ссылок Apple Music. gamdl умеет artist|album|playlist|song|music-video|post,
# но бот отправляет один файл, поэтому осмысленны только треки.
_MEDIA_TYPES = ("artist", "album", "playlist", "song", "music-video", "post")
_ID_RE = re.compile(r"^(?:[0-9]+|pl\.[0-9a-z]{32}|pl\.u-[a-zA-Z0-9]+)$", re.IGNORECASE)
_COUNTRY_RE = re.compile(r"^[a-z]{2}$", re.IGNORECASE)

DEFAULT_STOREFRONT = "us"

# Публичный поиск по каталогу Apple: нужен потому, что gamdl принимает только
# готовые ссылки и списка треков не отдаёт. Авторизации не требуют.
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"


def _http_host_re(host: str) -> re.Pattern:
    """Ссылка с любым поддоменом (geo., classical., www.) и любой схемой."""
    return re.compile(rf"^(?:https?://)?(?:[a-z0-9-]+\.)*{re.escape(host)}/", re.IGNORECASE)


_MUSIC_APPLE_RE = _http_host_re("music.apple.com")
_ITUNES_APPLE_RE = _http_host_re("itunes.apple.com")


def parse_apple_url(url: str, storefront: str = DEFAULT_STOREFRONT):
    """
    Разбирает ссылку Apple Music и приводит её к каноничному виду.

    gamdl принимает СТРОГО:
        https://music.apple.com/{код страны}/{тип}[/слаг]/{id}[?i=sub_id]
    Отклоняются: http вместо https, отсутствие кода страны, поддомены geo./itunes.
    Возвращает dict или None, если это не ссылка Apple Music.
    """
    url = (url or "").strip()

    # itunes.apple.com и geo.music.apple.com -> music.apple.com
    if _ITUNES_APPLE_RE.match(url):
        host = "music.apple.com"
        url = _ITUNES_APPLE_RE.sub(f"https://{host}/", url, count=1)
    elif _MUSIC_APPLE_RE.match(url):
        # classical.music.apple.com — отдельный каталог, его ID в обычном не разрешатся
        classical = bool(re.match(r"^(?:https?://)?classical\.", url, re.IGNORECASE))
        host = "classical.music.apple.com" if classical else "music.apple.com"
        url = _MUSIC_APPLE_RE.sub(f"https://{host}/", url, count=1)
    else:
        return None
    # После подстановки ссылка всегда начинается с https:// — gamdl http не принимает

    path, _, query = url.partition("?")
    segments = [s for s in path.split("/")[3:] if s]

    if not segments:
        return None

    if "/library/" in path.lower():
        return {"kind": "unsupported", "type": "library", "storefront": storefront}

    # Код страны может отсутствовать — тогда подставляем страну аккаунта
    if segments and _COUNTRY_RE.match(segments[0]):
        storefront = segments.pop(0).lower()

    if not segments or segments[0].lower() not in _MEDIA_TYPES:
        return {"kind": "unsupported", "type": segments[0] if segments else "?", "storefront": storefront}

    media_type = segments.pop(0).lower()

    # Осталось: [слаг] + id. Слаг отбрасываем — gamdl берёт страницу по id,
    # а вместе с ним уходят кириллица в URL и проблемы с кодированием.
    media_id = next((s for s in reversed(segments) if _ID_RE.match(s)), None)
    if not media_id:
        return {"kind": "unsupported", "type": media_type, "storefront": storefront}

    sub_id = None
    m = re.search(r"(?:^|&)i=([0-9]+)", query)
    if m:
        sub_id = m.group(1)

    canonical = f"https://{host}/{storefront}/{media_type}/{media_id}"
    if sub_id:
        canonical += f"?i={sub_id}"

    if media_type == "song" or sub_id:
        kind = "track"
    elif media_type == "album":
        kind = "album"
    else:
        kind = "unsupported"

    return {
        "kind": kind,
        "type": media_type,
        "storefront": storefront,
        "id": media_id,
        "sub_id": sub_id,
        "url": canonical,
    }


class AppleMusicError(Exception):
    """Ошибка Apple Music с готовым текстом для пользователя."""

    def __init__(self, message: str):
        super().__init__(message)
        self.user_message = message


def build_cookies_hint() -> str:
    return (
        "🍎 *Apple Music: нужны cookies*\n\n"
        "Скачивание работает по cookie `media-user-token` вашей подписки:\n\n"
        "1. Открой [music.apple.com](https://music.apple.com) в браузере, где вы вошли в аккаунт\n"
        "2. Расширением *Get cookies.txt LOCALLY* (Chrome) или *Export Cookies* (Firefox) "
        "выгрузи cookies в формате Netscape\n"
        "3. Положи файл на сервер как `/root/musicBot/cookies.txt`\n\n"
        "После этого просто пришлите ссылку на трек — бот проверит cookies сам."
    )


class AppleMusicDownloader:
    """
    Обёртка над gamdl (Apple Music).

    gamdl требует httpx>=0.28 и Pillow>=12, которые конфликтуют с зависимостями
    самого бота, поэтому он установлен в отдельное окружение gamdl-venv и
    вызывается как CLI-подпроцесс — так же, как rip для Qobuz.
    """

    # ALAC (Hi-Res) убран намеренно. Проверено на живом аккаунте: Apple отдаёт
    # поток, но отказывает в лицензии на расшифровку —
    #   GamdlApiResponseError: Error fetching license exchange data: {"status":-1002}
    # без wrapper-демона (Apple ID + пароль + 2FA). Попытка ALAC лишь тратила
    # время на каждой загрузке, поэтому качаем сразу AAC 256 kbps.
    # Если появится wrapper — добавить сюда ("alac", "Hi-Res (ALAC)") первым
    # и передать gamdl флаг --use-wrapper.
    CODEC_ATTEMPTS: Tuple[Tuple[str, str], ...] = (
        ("aac-web", "AAC 256 kbps"),
    )

    def __init__(self):
        self.download_dir = Config.APPLE_MUSIC_DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.gamdl_path = Config.APPLE_MUSIC_GAMDL
        self.cookies_path = Config.APPLE_MUSIC_COOKIES
        logger.info("✅ Сервис загрузки Apple Music (gamdl) инициализирован.")

    def is_configured(self) -> bool:
        """Готов ли сервис к работе: есть ли gamdl и cookies."""
        return self.gamdl_path.exists() and self.cookies_path.exists()

    def account_storefront(self) -> str:
        """
        Код страны аккаунта для ссылок без него (cookie itua).
        Нужен, потому что gamdl отвергает ссылки без сегмента страны.
        """
        try:
            from http.cookiejar import MozillaCookieJar

            jar = MozillaCookieJar(str(self.cookies_path))
            jar.load(ignore_discard=True, ignore_expires=True)
            for cookie in jar:
                if cookie.name == "itua" and _COUNTRY_RE.match(cookie.value or ""):
                    return cookie.value.lower()
        except Exception as e:
            logger.debug(f"Не удалось определить страну аккаунта из cookies: {e}")
        return DEFAULT_STOREFRONT

    def _check_ready(self):
        if not self.gamdl_path.exists():
            raise AppleMusicError(
                "❌ Apple Music: не найден gamdl. Установите его в `gamdl-venv` на сервере."
            )
        if not self.cookies_path.exists():
            raise AppleMusicError(build_cookies_hint())

    async def get_album_info(self, url: str) -> Optional[dict]:
        """
        Список треков альбома — для инлайн-клавиатуры выбора.

        gamdl умеет качать альбом целиком, но состава не отдаёт, поэтому
        треки берём из публичного iTunes Lookup API (entity=song).
        Страна — из cookies аккаунта: Apple отдаёт только регион подписки.
        """
        import httpx

        parsed = parse_apple_url(url, storefront=self.account_storefront())
        if not parsed or parsed["kind"] != "album":
            return None

        params = {
            "id": parsed["id"],
            "entity": "song",
            "limit": 200,
            "country": parsed["storefront"],
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(ITUNES_LOOKUP_URL, params=params)
            if response.status_code != 200:
                logger.warning(f"⚠️ Apple Music: список треков вернул {response.status_code}")
                return None
            results = response.json().get("results", [])
        except Exception as e:
            logger.warning(f"⚠️ Apple Music: ошибка получения альбома: {e}")
            return None

        album_title = ""
        artist = ""
        tracks = []
        for item in results:
            # Первым в ответе идёт сам альбом, дальше — его треки
            if item.get("wrapperType") == "collection":
                album_title = item.get("collectionName", "")
                artist = item.get("artistName", "")
                continue
            if item.get("wrapperType") != "track" or not item.get("trackViewUrl"):
                continue

            canonical = parse_apple_url(item["trackViewUrl"], storefront=parsed["storefront"])
            if not canonical or canonical["kind"] != "track":
                continue

            tracks.append(
                {
                    "title": item.get("trackName", ""),
                    "url": canonical["url"],
                    "disc": item.get("discNumber", 1) or 1,
                    "number": item.get("trackNumber", 0) or 0,
                }
            )

        if not tracks:
            return None

        # Порядок как на релизе: сначала диск, потом номер трека
        tracks.sort(key=lambda t: (t["disc"], t["number"]))
        for index, track in enumerate(tracks, 1):
            track["index"] = index

        return {
            "title": album_title or parsed["id"],
            "artist": artist,
            # ограничение как у Qobuz и Spotify: клавиатура не должна быть бесконечной
            "tracks": tracks[:50],
        }

    async def search_and_download_lucky(
        self,
        artist: str,
        title: str,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Ищет трек по метаданным и скачивает найденное.

        gamdl умеет только ссылки, поэтому ищем через публичный iTunes Search API
        (без авторизации) и отдаём найденный trackViewUrl ему. Страну берём из
        cookies аккаунта: Apple отдаёт лишь то, что есть в регионе подписки.
        """
        url = await self._search_track_url(artist, title)
        if not url:
            return None, None

        # iTunes отдаёт ссылку с трекингом (&uo=4); приводим к каноничному виду,
        # который gamdl принимает гарантированно
        parsed = parse_apple_url(url, storefront=self.account_storefront())
        if not parsed or parsed["kind"] != "track":
            logger.warning(f"⚠️ Apple Music: поиск вернул неожиданную ссылку {url}")
            return None, None

        logger.info(f"🔍 Apple Music: найден трек, скачиваю {parsed['url']}")
        return await self.download_track(parsed["url"])

    async def _search_track_url(self, artist: str, title: str) -> Optional[str]:
        import httpx

        query = f"{artist} {title}".strip()
        params = {
            "term": query,
            "entity": "song",
            "limit": 1,
            "country": self.account_storefront(),
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(ITUNES_SEARCH_URL, params=params)
            if response.status_code != 200:
                logger.warning(f"⚠️ Apple Music: поиск вернул {response.status_code}")
                return None
            results = response.json().get("results", [])
            if not results:
                logger.info(f"ℹ️ Apple Music: по запросу '{query}' ничего не найдено")
                return None
            return results[0].get("trackViewUrl")
        except Exception as e:
            logger.warning(f"⚠️ Apple Music: ошибка поиска: {e}")
            return None

    async def download_track(
        self,
        url: str,
        track_index: Optional[int] = None,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Скачивает трек по ссылке music.apple.com.

        Ссылка на альбом тоже принимается: с track_index (нумерация с 1) берётся
        конкретный трек, без него — первый (весь альбом качает вызывающая сторона,
        чтобы отправлять файлы по мере готовности).
        """
        parsed = parse_apple_url(url, storefront=self.account_storefront())
        if not parsed:
            raise AppleMusicError("❌ Apple Music: не удалось разобрать ссылку.")

        if parsed["kind"] == "track":
            url = parsed["url"]

        elif parsed["kind"] == "album":
            album_info = await self.get_album_info(url)
            if not album_info or not album_info["tracks"]:
                raise AppleMusicError("❌ Apple Music: не удалось получить список треков альбома.")
            index = track_index or 1
            if not 1 <= index <= len(album_info["tracks"]):
                raise AppleMusicError(f"❌ Apple Music: в альбоме нет трека №{index}.")
            url = album_info["tracks"][index - 1]["url"]

        else:
            raise AppleMusicError(
                f"🍎 Apple Music: ссылки типа «{parsed['type']}» не поддерживаются.\n\n"
                "Пришлите ссылку на трек или альбом."
            )

        self._check_ready()
        logger.info(f"⬇️ Apple Music: скачивание {url}")

        for codec, label in self.CODEC_ATTEMPTS:
            logger.info(f"🎧 Apple Music: пробую качество {label}")
            self._clear_temp_dir()

            if progress_callback:
                await progress_callback(10.0)

            audio_file, cover_file = await self._run_gamdl(url, codec, progress_callback)
            if audio_file:
                if self._is_valid_audio(audio_file):
                    logger.info(f"✅ Apple Music: получен файл {audio_file.name} ({label})")
                    return audio_file, cover_file
                # У gamdl бывают обрезанные/битые .m4a — отдавать такое нельзя,
                # поэтому пробуем следующее качество.
                logger.warning(
                    f"⚠️ Apple Music: файл в {label} повреждён или пуст ({audio_file.name}) — пробую следующее"
                )

            logger.warning(f"⚠️ Apple Music: качество {label} недоступно, пробую следующее")

        return None, None

    async def _run_gamdl(
        self,
        url: str,
        codec: str,
        progress_callback: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        log_file = self.download_dir / "gamdl.log"
        command = [
            str(self.gamdl_path),
            "--no-config-file",           # чтобы чужой ~/.gamdl/config.ini не влиял
            "-c", str(self.cookies_path),
            "-o", str(self.download_dir),
            "--temp-path", str(self.download_dir / ".tmp"),
            "--song-codec-priority", codec,
            "--save-cover",               # отдельный файл обложки — бот шлёт её фото
            "--no-synced-lyrics",
            "--overwrite",
            "--log-level", "WARNING",
            "--log-file", str(log_file),
            url,
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            # Обязательно: у gamdl есть интерактивные TUI-промпты (inquirerpy).
            # Без закрытого stdin он может навсегда повесить воркер.
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        all_output: List[str] = []

        async def _read_and_wait():
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="ignore").strip()
                if line:
                    all_output.append(line)
                    logger.debug(f"gamdl: {line}")
            await process.wait()

        try:
            await asyncio.wait_for(_read_and_wait(), timeout=GAMDL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Apple Music: gamdl превысил таймаут {GAMDL_TIMEOUT}s — убиваю подпроцесс")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            return None, None

        output_text = "\n".join(all_output)
        if log_file.exists():
            try:
                output_text += "\n" + log_file.read_text(errors="ignore")
            except OSError:
                pass

        self._raise_if_fatal(output_text)

        if process.returncode != 0:
            logger.error(
                f"❌ Apple Music: gamdl завершился с кодом {process.returncode}:\n{output_text[-2000:]}"
            )

        # Код возврата у gamdl не информативен: он ловит ошибки трека,
        # пишет 'Skipping ...' и всё равно выходит с 0. Поэтому единственный
        # надёжный признак успеха — реально появившийся файл.
        if "Skipping " in output_text:
            for line in output_text.splitlines():
                if "Skipping " in line:
                    logger.warning(f"⚠️ Apple Music: {line.strip()}")

        audio_file, cover_file = self._find_downloaded_files()
        if audio_file and progress_callback:
            await progress_callback(100.0)
        return audio_file, cover_file

    def _raise_if_fatal(self, output_text: str):
        """Отличает проблемы с доступом от обычных сбоев скачивания."""
        lowered = output_text.lower()

        # Точный текст gamdl: '"media-user-token" cookie not found in cookies'
        if "cookie not found in cookies" in lowered:
            raise AppleMusicError(
                "❌ Apple Music: в cookies.txt нет cookie `media-user-token`.\n"
                "Выгрузите cookies заново с сайта music.apple.com.\n\n" + build_cookies_hint()
            )
        if "no active apple music subscription" in lowered:
            raise AppleMusicError(
                "❌ Apple Music: у аккаунта нет активной подписки Apple Music."
            )
        if "index.js" in lowered and ("error" in lowered or "token" in lowered):
            raise AppleMusicError(
                "❌ Apple Music: Apple изменил свой веб-интерфейс, и gamdl не смог получить токен.\n"
                "Обычно лечится обновлением gamdl на сервере."
            )
        if "resource with requested id was not found" in lowered or "status code: 404" in lowered:
            raise AppleMusicError(
                "❌ Apple Music: трек не найден в каталоге вашего аккаунта.\n\n"
                "Apple отдаёт только то, что есть в регионе подписки. Если релиз "
                "доступен лишь в другом регионе (например, только в RU, а подписка US) — "
                "скачать его нельзя ни по какой ссылке.\n\n"
                "Попробуйте найти этот трек на Qobuz."
            )

    @staticmethod
    def _is_valid_audio(audio_file: Path) -> bool:
        """Файл читается как аудио и не обрезан."""
        try:
            if audio_file.stat().st_size < 10_000:
                return False
            audio = mutagen.File(audio_file)
            return bool(audio and audio.info and getattr(audio.info, "length", 0) > 0)
        except Exception as e:
            logger.warning(f"⚠️ Apple Music: не удалось прочитать {audio_file.name}: {e}")
            return False

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        """Ищет самый свежий аудиофайл и обложку рядом с ним."""
        audio_files = [
            f
            for f in self.download_dir.glob("**/*.*")
            if f.is_file()
            and f.suffix.lower() in {".m4a", ".mp4", ".flac", ".mp3"}
            and ".tmp" not in f.parts
        ]
        if not audio_files:
            return None, None

        audio_file = max(audio_files, key=lambda f: f.stat().st_mtime)

        cover_file = None
        for cover in sorted(audio_file.parent.glob("*")):
            if cover.is_file() and cover.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                cover_file = cover
                break

        return audio_file, cover_file

    def _clear_temp_dir(self):
        """Полная очистка рабочей папки перед новым скачиванием."""
        for item in self.download_dir.glob("*"):
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except OSError as e:
                logger.warning(f"⚠️ Не удалось удалить {item}: {e}")
