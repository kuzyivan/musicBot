"""
Spotify Canvas — короткое вертикальное видео (3–8 сек), которое Spotify
проигрывает поверх обложки в мобильном приложении.

Официального API нет, поэтому используется тот же путь, что и у плагина
yt-dlp-SpotifyCanvas:
  1. cookie sp_dc из браузера → TOTP-секрет → access token веб-плеера;
  2. POST в приватный canvaz-cache (protobuf) → ссылка на .cnvs.mp4;
  3. скачивание mp4 и (по запросу) конвертация в GIF через ffmpeg.

Всё это необязательный бонус: без cookie, при смене приватного API или
отсутствии Canvas у трека загрузка песни продолжается как обычно.
"""
from pathlib import Path
from typing import Iterable, Optional, Tuple
from config import Config
import logging
import asyncio
import hashlib
import hmac
import re
import struct
import time

logger = logging.getLogger(__name__)

CANVAS_ENDPOINT = "https://spclient.wg.spotify.com/canvaz-cache/v0/canvases"
TOKEN_ENDPOINT = "https://open.spotify.com/api/token"

# Каталог TOTP-секретов обновляется автоматически. Если он недоступен,
# остаётся запасной секрет версии 61 — на нём бот работал до этого.
SECRET_CATALOGS = (
    "https://code.thetadev.de/ThetaDev/spotify-secrets/raw/branch/main/secrets/secretDict.json",
    "https://raw.githubusercontent.com/xyloflake/spot-secrets-go/refs/heads/main/secrets/secretDict.json",
)
FALLBACK_SECRET_VERSION = 61
FALLBACK_SECRET_BYTES = (
    44, 55, 47, 42, 70, 40, 34, 114, 76, 74, 50, 111, 120,
    97, 75, 76, 94, 102, 43, 69, 49, 120, 118, 80, 64, 78,
)
SECRET_CATALOG_TTL = 3600  # сек

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

# Типы Canvas из canvas.proto: 0 — статичная картинка, 1–4 — видео/GIF.
_VIDEO_TYPES = {1, 2, 3, 4}

MAX_CANVAS_BYTES = 30 * 1024 * 1024
MAX_GIF_BYTES = 45 * 1024 * 1024
# 400px/12 fps/96 цветов — ~4–5 МБ на 5-секундный Canvas. Полноразмерный
# GIF (720px/15 fps) весил бы вдвое больше, а Telegram всё равно пережимает его.
GIF_WIDTH = 400
GIF_FPS = 12
GIF_COLORS = 96

# Кэш каталога секретов общий для всех экземпляров: файл один и тот же.
_secret_cache: Optional[Tuple[int, Tuple[int, ...], float]] = None


class SpotifyCanvasError(Exception):
    """Ошибка получения Canvas с готовым текстом для лога."""


# --- Netscape cookies ---

def parse_spotify_cookies(path: Path) -> dict:
    """
    Читает sp_dc/sp_key из Netscape-файла cookies.

    Понимает и обычный формат с табами, и файлы, где табы при копировании
    заменились пробелами (та же беда, что и у cookies Apple Music).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        logger.debug(f"Spotify Canvas: cookies не прочитаны ({e})")
        return {}

    cookies = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # Chrome/Get cookies.txt помечают HttpOnly-строки префиксом #HttpOnly_,
        # а sp_dc и sp_key как раз HttpOnly — обычный "#" их бы отбросил.
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        if not line:
            continue

        # На случай строки вида "sp_dc=..." вместо Netscape-таблицы
        if "=" in line and "\t" not in line and not re.search(r"\s{2,}", line):
            name, _, value = line.partition("=")
            if name.strip() in {"sp_dc", "sp_key"} and value.strip():
                cookies[name.strip()] = value.strip()
            continue

        fields = re.split(r"\t+|\s{2,}", line)
        if len(fields) >= 7:
            name, value = fields[-2], fields[-1]
            if name in {"sp_dc", "sp_key"} and value:
                cookies[name] = value

    return cookies


# --- TOTP ---

def _totp_secret_key(secret_bytes: Iterable[int]) -> bytes:
    """
    Ключ TOTP по алгоритму веб-плеера Spotify: XOR байтов секрета с
    (i % 33 + 9), затем десятичная запись каждого байта как ASCII.
    """
    return b"".join(
        str(byte ^ (i % 33 + 9)).encode()
        for i, byte in enumerate(secret_bytes)
    )


def _totp_code(secret_bytes: Iterable[int], timestamp: Optional[int] = None) -> str:
    """6-значный TOTP (SHA-1, шаг 30 сек) без внешних зависимостей."""
    key = _totp_secret_key(secret_bytes)
    counter = int(timestamp if timestamp is not None else time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


async def _fetch_secret_catalog(client) -> Optional[Tuple[int, Tuple[int, ...]]]:
    """Возвращает самый свежий секрет из первого доступного каталога."""
    for url in SECRET_CATALOGS:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                continue
            catalog = response.json()
            versions = []
            for version, values in catalog.items():
                try:
                    number = int(version)
                    secret = tuple(int(v) for v in values)
                except (TypeError, ValueError):
                    continue
                if secret and all(0 <= b <= 255 for b in secret):
                    versions.append((number, secret))
            if versions:
                return max(versions, key=lambda item: item[0])
        except Exception as e:
            logger.debug(f"Spotify Canvas: каталог {url} недоступен: {e}")
    return None


async def _latest_totp_secret(client) -> Tuple[int, Tuple[int, ...]]:
    global _secret_cache

    if _secret_cache and time.time() - _secret_cache[2] < SECRET_CATALOG_TTL:
        return _secret_cache[0], _secret_cache[1]

    fetched = await _fetch_secret_catalog(client)
    if fetched:
        _secret_cache = (fetched[0], fetched[1], time.time())
        return fetched

    logger.warning("⚠️ Spotify Canvas: каталог TOTP-секретов недоступен, беру запасной")
    return FALLBACK_SECRET_VERSION, FALLBACK_SECRET_BYTES


# --- Protobuf (только нужные поля, без зависимости protobuf) ---

def _varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _encode_canvas_request(track_id: str) -> bytes:
    uri = f"spotify:track:{track_id}".encode()
    entity = b"\x0a" + _varint(len(uri)) + uri
    return b"\x0a" + _varint(len(entity)) + entity


def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError("битый varint")


def _iter_fields(data: bytes):
    """Итерирует (номер поля, wire type, значение) в protobuf-сообщении."""
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        field, wire = key >> 3, key & 0x07
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        elif wire == 2:
            length, pos = _read_varint(data, pos)
            value, pos = data[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = data[pos:pos + 4], pos + 4
        else:
            return
        if pos > len(data):
            raise ValueError("обрезанное protobuf-сообщение")
        yield field, wire, value


def _parse_canvases(data: bytes) -> list:
    """
    Достаёт из EntityCanvazResponse список (тип, url).

    Canvaz: 1 id, 2 url, 4 type. Остальные поля пропускаются.
    """
    canvases = []
    for field, wire, payload in _iter_fields(data):
        if field != 1 or wire != 2:
            continue
        canvas_type, url = 1, None
        for inner_field, inner_wire, inner_value in _iter_fields(payload):
            if inner_field == 2 and inner_wire == 2:
                url = inner_value.decode("utf-8", errors="ignore")
            elif inner_field == 4 and inner_wire == 0:
                canvas_type = inner_value
        if url:
            canvases.append((canvas_type, url))
    return canvases


def _is_allowed_canvas_url(url: str) -> bool:
    """Canvas обязан лежать на CDN Spotify: качать любой URL из API нельзя."""
    return bool(re.match(
        r"^https://(?:[\w.-]+\.)?(?:scdn\.co|spotifycdn\.com|spotify\.com)/",
        url,
    ))


# --- основной сервис ---

class SpotifyCanvasDownloader:
    def __init__(self, cookies_path: Optional[Path] = None):
        self.cookies_path = Path(cookies_path or Config.SPOTIFY_COOKIES)
        self._cookies = parse_spotify_cookies(self.cookies_path)
        self._token: Optional[str] = None
        self._token_expires_at = 0.0

    def is_configured(self) -> bool:
        return bool(self._cookies.get("sp_dc"))

    async def _access_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._token_expires_at:
            return self._token

        sp_dc = self._cookies.get("sp_dc")
        if not sp_dc:
            raise SpotifyCanvasError(
                f"нет cookie sp_dc в {self.cookies_path.name}"
            )

        cookie = f"sp_dc={sp_dc}"
        if self._cookies.get("sp_key"):
            cookie += f"; sp_key={self._cookies['sp_key']}"

        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            version, secret = await _latest_totp_secret(client)
            code = _totp_code(secret)
            response = await client.get(
                TOKEN_ENDPOINT,
                params={
                    "reason": "init",
                    "productType": "web-player",
                    "totp": code,
                    "totpServer": code,
                    "totpVer": str(version),
                },
                headers={"Cookie": cookie, "User-Agent": USER_AGENT},
            )

        if response.status_code == 429:
            raise SpotifyCanvasError("Spotify ограничил частоту запросов токена (429)")
        if response.status_code != 200:
            raise SpotifyCanvasError(f"токен не получен: HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as e:
            raise SpotifyCanvasError(f"токен не разобран: {e}")

        token = data.get("accessToken")
        if not token or data.get("isAnonymous"):
            raise SpotifyCanvasError("Spotify вернул анонимный токен — sp_dc недействителен")

        self._token = token
        expires_ms = int(data.get("accessTokenExpirationTimestampMs") or 0)
        # 30 сек запаса, чтобы не отправить запрос с истекающим токеном
        self._token_expires_at = (expires_ms / 1000 - 30) if expires_ms else time.time() + 1800
        return token

    async def get_canvas_url(self, track_id: str) -> Optional[str]:
        """Возвращает ссылку на mp4 Canvas или None, если Canvas нет."""
        import httpx

        body = _encode_canvas_request(track_id)
        headers = {"Content-Type": "application/x-protobuf"}

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            token = await self._access_token()
            response = await client.post(
                CANVAS_ENDPOINT,
                content=body,
                headers={**headers, "Authorization": f"Bearer {token}"},
            )
            if response.status_code == 401:
                token = await self._access_token(force=True)
                response = await client.post(
                    CANVAS_ENDPOINT,
                    content=body,
                    headers={**headers, "Authorization": f"Bearer {token}"},
                )

        if response.status_code == 429:
            raise SpotifyCanvasError("Spotify ограничил частоту запросов Canvas (429)")
        if response.status_code != 200:
            raise SpotifyCanvasError(f"canvaz-cache вернул HTTP {response.status_code}")

        canvases = _parse_canvases(response.content)
        if not canvases:
            return None

        # Сначала видео, только потом статичная картинка: GIF из неё не нужен.
        canvases.sort(key=lambda item: item[0] not in _VIDEO_TYPES)
        for canvas_type, url in canvases:
            if canvas_type == 0:
                continue
            if not _is_allowed_canvas_url(url):
                logger.warning(f"⚠️ Spotify Canvas: подозрительный URL пропущен: {url[:120]}")
                continue
            return url
        return None

    async def download(self, track_id: str, dest_dir: Path) -> Optional[Path]:
        """Скачивает Canvas в dest_dir. Возвращает путь к mp4 или None."""
        import httpx

        url = await self.get_canvas_url(track_id)
        if not url:
            logger.info(f"ℹ️ Spotify Canvas: у трека {track_id} нет видео")
            return None

        dest_dir.mkdir(parents=True, exist_ok=True)
        # расширение из URL может быть .cnvs.mp4; суффикс всегда .mp4
        target = dest_dir / f"canvas_{track_id}.mp4"
        partial = target.with_suffix(".mp4.part")

        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise SpotifyCanvasError(f"CDN вернул HTTP {response.status_code}")
                    size = 0
                    with open(partial, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_CANVAS_BYTES:
                                raise SpotifyCanvasError("Canvas больше лимита")
                            f.write(chunk)
            if partial.stat().st_size < 1024:
                raise SpotifyCanvasError("Canvas подозрительно маленький")
            partial.replace(target)
            logger.info(f"🎬 Spotify Canvas: скачан {target.name} ({target.stat().st_size // 1024} КБ)")
            return target
        except Exception:
            if partial.exists():
                partial.unlink(missing_ok=True)
            raise

    @staticmethod
    async def to_gif(video_path: Path) -> Optional[Path]:
        """
        Конвертирует mp4 в GIF через ffmpeg (палитра из двух проходов).

        Возвращает путь к gif или None, если ffmpeg недоступен/не справился.
        """
        gif_path = video_path.with_suffix(".gif")
        command = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-an",
            "-vf", (
                f"fps={GIF_FPS},scale={GIF_WIDTH}:-2:flags=lanczos,"
                f"split[a][b];[a]palettegen=max_colors={GIF_COLORS}:stats_mode=diff[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
            ),
            "-loop", "0",
            str(gif_path),
        ]

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("⏱️ Spotify Canvas: ffmpeg не успел сконвертировать GIF")
            if process:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            return None
        except FileNotFoundError:
            logger.error("❌ Spotify Canvas: ffmpeg не найден")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Spotify Canvas: ошибка конвертации в GIF: {e}")
            return None

        if process.returncode != 0 or not gif_path.exists():
            logger.error(
                "❌ Spotify Canvas: ffmpeg завершился с ошибкой: "
                f"{(stderr or b'').decode('utf-8', errors='ignore')[-800:]}"
            )
            gif_path.unlink(missing_ok=True)
            return None

        if gif_path.stat().st_size > MAX_GIF_BYTES:
            logger.warning("⚠️ Spotify Canvas: GIF больше лимита Telegram")
            gif_path.unlink(missing_ok=True)
            return None

        logger.info(f"🎞️ Spotify Canvas: GIF готов ({gif_path.stat().st_size // 1024} КБ)")
        return gif_path


async def canvas_to_gif(video_path: Path) -> Optional[Path]:
    """Конвертация Canvas в GIF без создания клиента Spotify."""
    return await SpotifyCanvasDownloader.to_gif(video_path)
