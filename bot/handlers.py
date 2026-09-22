from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ContextTypes, CallbackQueryHandler
from services.downloader import QobuzDownloader, QobuzAuthError
from services import whitelist
from services.spotify_downloader import SpotifyDownloader, SpotifyError, parse_spotify_url
from services.apple_music_downloader import AppleMusicDownloader, AppleMusicError, parse_apple_url
from services.sources import detect_source
from services.file_manager import FileManager
from services.recognizer import AudioRecognizer
from config import Config
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import shutil
import mutagen
import asyncio
from io import BytesIO

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    return whitelist.is_allowed(user_id, Config.ADMIN_USER_ID)


async def _typing_loop(bot, chat_id: int, stop_event: asyncio.Event):
    """Шлёт chat action каждые 4 сек пока идёт загрузка."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


# --- Вспомогательные функции ---

def embed_cover_art(audio_path: Path, cover_path: Optional[Path]):
    if not all([audio_path, cover_path, audio_path.exists(), cover_path.exists()]):
        return
    logger.info(f"🖼️ Встраивание обложки {cover_path.name} в файл {audio_path.name}...")
    temp_output_path = audio_path.with_suffix(f".temp{audio_path.suffix}")
    try:
        command = [
            "ffmpeg", "-i", str(audio_path), "-i", str(cover_path), "-map", "0:a",
            "-map", "1:v", "-c", "copy", "-disposition:v:0", "attached_pic",
            "-id3v2_version", "3", str(temp_output_path)
        ]
        subprocess.run(command, check=True, capture_output=True)
        shutil.move(str(temp_output_path), str(audio_path))
        logger.info("✅ Обложка успешно встроена.")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Не удалось встроить обложку с помощью ffmpeg: {e.stderr.decode()}")
    except Exception as e:
        logger.error(f"❌ Не удалось встроить обложку: {e}")
    finally:
        if temp_output_path.exists(): temp_output_path.unlink()


def _md_escape(value) -> str:
    """
    Экранирует символы, ломающие parse_mode='Markdown'.

    Названия треков и артистов содержат _ * ` [ — без экранирования Telegram
    отклоняет сообщение целиком с ошибкой разбора разметки, и пользователь
    не получает вообще ничего.
    """
    return re.sub(r"([_*`\[\]])", r"\\\1", str(value))


def has_embedded_cover(audio_path: Path) -> bool:
    """
    Проверяет, есть ли в файле встроенная обложка.
    gamdl (Apple Music) и streamrip (Qobuz) вшивают её сами, и повторное
    встраивание через ffmpeg только раздувает файл и тратит время.
    """
    try:
        audio = mutagen.File(audio_path)
        if not audio:
            return False
        if getattr(audio, "pictures", None):
            return True
        tags = audio.tags or {}
        if "covr" in tags:
            return True
        if hasattr(tags, "getall") and tags.getall("APIC"):
            return True
    except Exception as e:
        logger.warning(f"⚠️ Не удалось проверить встроенную обложку: {e}")
    return False


def convert_to_mp3(file_path: Path) -> Optional[Path]:
    mp3_path = file_path.with_suffix(".mp3")
    logger.info(f"🎵 Конвертация файла {file_path.name} в MP3...")
    try:
        command = [
            "ffmpeg", "-i", str(file_path), "-map", "0:a:0", "-b:a", "320k",
            "-map", "0:v?", "-c:v", "copy", "-id3v2_version", "3", str(mp3_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        logger.info(f"✅ Файл успешно сконвертирован в {mp3_path.name}")
        return mp3_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Ошибка конвертации ffmpeg: {e.stderr.decode()}")
        return None

TELEGRAM_PHOTO_LIMIT_BYTES = 10 * 1024 * 1024

def prepare_cover_for_telegram(cover_path: Path) -> Optional[Path]:
    """
    Telegram принимает фото до 10 МБ. Если обложка больше — сжимаем через ffmpeg.
    Возвращает путь к файлу, готовому к отправке (или исходный, если он влезает).
    """
    try:
        if cover_path.stat().st_size <= TELEGRAM_PHOTO_LIMIT_BYTES:
            return cover_path
    except OSError:
        return None

    compressed_path = cover_path.with_suffix(".tg.jpg")
    for max_width in (3000, 2000, 1200):
        command = [
            "ffmpeg", "-y", "-i", str(cover_path),
            "-vf", f"scale='min({max_width},iw)':-2",
            "-q:v", "3", str(compressed_path)
        ]
        try:
            subprocess.run(command, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Не удалось сжать обложку с помощью ffmpeg: {e.stderr.decode()}")
            break
        if compressed_path.exists() and compressed_path.stat().st_size <= TELEGRAM_PHOTO_LIMIT_BYTES:
            return compressed_path
    if compressed_path.exists():
        compressed_path.unlink()
    return None

QUALITY_HIERARCHY = {
    "HI-RES (Max)": 27,
    "HI-RES (<96kHz)": 7,
    "CD (16-bit)": 6,
    "MP3 (320 kbps)": 5,
}

# --- Команды Start/Help ---

def _token_expired_message() -> str:
    return (
        "🔑 *Токен Qobuz истёк* — нужно обновить.\n\n"
        "*Как получить новый токен:*\n"
        "1. Открой [play.qobuz.com](https://play.qobuz.com) в браузере и войди в аккаунт\n"
        "2. Нажми `F12` → вкладка *Network*\n"
        "3. Обнови страницу (`F5`)\n"
        "4. В строке поиска запросов введи `user/login`\n"
        "5. Кликни на найденный запрос → вкладка *Headers*\n"
        "6. Скопируй значение заголовка `X-User-Auth-Token`\n\n"
        "Затем отправь боту:\n"
        "`/settoken ВСТАВЬ_ТОКЕН_СЮДА`"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Я бот версии 2.0 и могу скачивать треки с Qobuz, Spotify и Apple Music. 🚀")


async def set_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.ADMIN_USER_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    token = " ".join(context.args).strip() if context.args else ""
    if not token:
        await update.message.reply_text("Использование: /settoken <токен>")
        return

    # Обновляем .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    lines = env_path.read_text().splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("QOBUZ_AUTH_TOKEN="):
            lines[i] = f"QOBUZ_AUTH_TOKEN={token}"
            updated = True
            break
    if not updated:
        lines.append(f"QOBUZ_AUTH_TOKEN={token}")
    env_path.write_text("\n".join(lines) + "\n")

    # Обновляем конфиг streamrip
    streamrip_cfg = Path("/root/.config/streamrip/config.toml")
    if streamrip_cfg.exists():
        cfg_text = streamrip_cfg.read_text()
        cfg_text = re.sub(
            r'(password_or_token\s*=\s*)"[^"]*"',
            f'\\1"{token}"',
            cfg_text,
        )
        streamrip_cfg.write_text(cfg_text)

    # Обновляем в памяти без перезапуска
    Config.QOBUZ_AUTH_TOKEN = token

    await update.message.reply_text("✅ Токен Qobuz обновлён.")
    logger.info(f"🔑 Токен Qobuz обновлён пользователем {update.effective_user.id}")


async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.ADMIN_USER_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Использование: /adduser <user_id>")
        return
    user_id = int(context.args[0])
    if whitelist.add(user_id):
        await update.message.reply_text(f"✅ Пользователь `{user_id}` добавлен в whitelist.", parse_mode="Markdown")
        logger.info(f"➕ Добавлен в whitelist: {user_id}")
    else:
        await update.message.reply_text(f"ℹ️ Пользователь `{user_id}` уже в whitelist.", parse_mode="Markdown")


async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.ADMIN_USER_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Использование: /removeuser <user_id>")
        return
    user_id = int(context.args[0])
    if user_id == Config.ADMIN_USER_ID:
        await update.message.reply_text("⛔ Нельзя удалить администратора.")
        return
    if whitelist.remove(user_id):
        await update.message.reply_text(f"✅ Пользователь `{user_id}` удалён из whitelist.", parse_mode="Markdown")
        logger.info(f"➖ Удалён из whitelist: {user_id}")
    else:
        await update.message.reply_text(f"ℹ️ Пользователя `{user_id}` нет в whitelist.", parse_mode="Markdown")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != Config.ADMIN_USER_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return
    users = whitelist.all_users()
    lines = [f"👤 Администратор: `{Config.ADMIN_USER_ID}` _(всегда разрешён)_"]
    if users:
        lines.append("\n📋 Whitelist:")
        for uid in sorted(users):
            lines.append(f"• `{uid}`")
    else:
        lines.append("\n📋 Whitelist пуст.")
    lines.append(f"\n➕ /adduser <id>\n➖ /removeuser <id>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек (Qobuz, Spotify или Apple Music)\n"
        "Или просто отправь аудио для распознавания."
    )

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ЗАГРУЗКИ ---

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    url = context.args[0] if context.args else getattr(update.message, 'text', '').strip()
    if not url: return

    source = detect_source(url)

    if source == "qobuz":
        if "/album/" in url:
            await _show_qobuz_album_tracks(update, context, url)
        else:
            await _download_qobuz(update, context, url)
    elif source == "spotify":
        parsed = parse_spotify_url(url)
        if parsed and parsed["kind"] == "album":
            await _show_spotify_album_tracks(update, context, url)
        else:
            await _download_spotify(update, context, url)
    elif source == "apple":
        parsed = parse_apple_url(url, storefront=AppleMusicDownloader().account_storefront())
        if parsed and parsed["kind"] == "album":
            await _show_apple_album_tracks(update, context, url)
        else:
            await _download_apple_music(update, context, url)
    else:
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на Qobuz, Spotify или Apple Music.")


async def _show_qobuz_album_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Показывает список треков альбома с кнопками."""
    downloader = QobuzDownloader()
    sent_message = await update.message.reply_text("⏳ Получаю список треков альбома...")
    
    album_info = await downloader.get_album_info(url)
    if not album_info or not album_info['tracks']:
        await sent_message.edit_text("⚠️ Не удалось получить список треков. Начинаю скачивание всего релиза...")
        await _download_qobuz(update, context, url)
        return

    text = f"💿 **{album_info['artist']} — {album_info['title']}**\n\nВыберите трек для скачивания:"
    
    keyboard = []
    current_row = []
    for track in album_info['tracks']:
        button = InlineKeyboardButton(f"{track['index']}. {track['title']}", callback_data=f"qdl:{track['index']}")
        current_row.append(button)
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)
    
    keyboard.append([InlineKeyboardButton("📥 Скачать весь альбом", callback_data="qdl:all")])
    context.user_data['last_album_url'] = url
    reply_markup = InlineKeyboardMarkup(keyboard)
    await sent_message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def _show_spotify_album_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Показывает список треков альбома Spotify с кнопками."""
    downloader = SpotifyDownloader()
    sent_message = await update.message.reply_text("⏳ Spotify: получаю список треков альбома...")

    album_info = downloader.get_album_info(url)
    if not album_info or not album_info["tracks"]:
        await sent_message.edit_text("❌ Spotify: не удалось получить список треков альбома.")
        return

    text = (
        f"*{_md_escape(album_info['title'])}*\n"
        f"{_md_escape(album_info['artist'])}\n\n"
        "Выберите трек:"
    )

    keyboard = []
    current_row = []
    for track in album_info["tracks"]:
        button = InlineKeyboardButton(
            f"{track['index']}. {track['title']}", callback_data=f"sdl:{track['index']}"
        )
        current_row.append(button)
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)

    keyboard.append([InlineKeyboardButton("📥 Скачать весь альбом", callback_data="sdl:all")])
    context.user_data["last_spotify_album_url"] = url
    await sent_message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_allowed(update.effective_user.id):
        await query.edit_message_text("⛔ Нет доступа.")
        return
    data = query.data

    if data.startswith("sdl:"):
        url = context.user_data.get("last_spotify_album_url")
        if not url:
            await query.edit_message_text("❌ Ошибка: ссылка потеряна. Отправьте её заново.")
            return
        action = data.split(":", 1)[1]
        if action == "all":
            await query.edit_message_text("⏳ Скачиваю весь альбом...")
            await _download_spotify_album(update, context, url)
        else:
            await query.edit_message_text(f"⏳ Скачиваю трек №{action}...")
            await _download_spotify(update, context, url, track_index=int(action))
        return

    if data.startswith("adl:"):
        url = context.user_data.get("last_apple_album_url")
        if not url:
            await query.edit_message_text("❌ Ошибка: ссылка потеряна. Отправьте её заново.")
            return
        action = data.split(":", 1)[1]
        if action == "all":
            await query.edit_message_text("⏳ Скачиваю весь альбом...")
            await _download_apple_album(update, context, url)
        else:
            await query.edit_message_text(f"⏳ Скачиваю трек №{action}...")
            await _download_apple_music(update, context, url, track_index=int(action))
        return

    if not data.startswith("qdl:"): return
    url = context.user_data.get('last_album_url')
    if not url:
        await query.edit_message_text("❌ Ошибка: ссылка потеряна. Отправьте её заново.")
        return
    action = data.split(":")[1]
    if action == "all":
        await query.edit_message_text("⏳ Начинаю скачивание всего альбома...")
        await _download_qobuz(update, context, url)
    else:
        track_index = int(action)
        await query.edit_message_text(f"⏳ Начинаю скачивание трека №{track_index}...")
        await _download_qobuz(update, context, url, track_index=track_index)


async def _download_qobuz(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, track_index: Optional[int] = None):
    downloader = QobuzDownloader()
    file_manager = FileManager()
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Подготовка к скачиванию...")
    
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context.bot, chat_id, stop_typing))
    try:
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            base_text = f"💿 Qobuz: Качество {quality_name}\n"
            if track_index: base_text += f"🎵 Трек №{track_index}\n"
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"{base_text}⏳ Скачиваю...")

            audio_file, cover_file = await downloader.download_track(url, quality_id, track_index=track_index)
            if audio_file:
                await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url, "Qobuz")
                return
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Qobuz: Не удалось скачать файл.")
    except QobuzAuthError:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=_token_expired_message())
    except Exception as e:
        logger.exception(f"❌ Qobuz: Ошибка: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Qobuz: Ошибка: {e}")
    finally:
        stop_typing.set()
        typing_task.cancel()


async def _show_apple_album_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """Показывает список треков альбома Apple Music с кнопками."""
    downloader = AppleMusicDownloader()
    sent_message = await update.message.reply_text("⏳ Apple Music: получаю список треков альбома...")

    album_info = await downloader.get_album_info(url)
    if not album_info or not album_info["tracks"]:
        await sent_message.edit_text("❌ Apple Music: не удалось получить список треков альбома.")
        return

    text = (
        f"*{_md_escape(album_info['title'])}*\n"
        f"{_md_escape(album_info['artist'])}\n\n"
        "Выберите трек:"
    )

    keyboard = []
    current_row = []
    for track in album_info["tracks"]:
        button = InlineKeyboardButton(
            f"{track['index']}. {track['title']}", callback_data=f"adl:{track['index']}"
        )
        current_row.append(button)
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)

    keyboard.append([InlineKeyboardButton("📥 Скачать весь альбом", callback_data="adl:all")])
    context.user_data["last_apple_album_url"] = url
    await sent_message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


async def _download_apple_music(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, track_index: Optional[int] = None):
    """
    Скачивание из Apple Music через gamdl.

    Ссылку приводит к каноничному виду уже сервис: gamdl принимает строго
    https, только домены music/classical.music.apple.com и обязательно с кодом
    страны. Поэтому ссылки вида geo.music.apple.com, itunes.apple.com, http://
    или без /ru/ иначе падали бы с ошибкой разбора URL.
    """
    downloader = AppleMusicDownloader()
    # Вызывается и из кнопок, где update.message отсутствует
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context.bot, chat_id, stop_typing))
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Apple Music: готовлю скачивание...")
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text="🍎 Apple Music: скачиваю AAC 256 kbps...",
        )

        audio_file, cover_file = await downloader.download_track(url, track_index=track_index)

        if audio_file:
            await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url, "Apple Music")
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="❌ Apple Music: не удалось скачать файл.",
            )
    except AppleMusicError as e:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=e.user_message,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.exception(f"❌ Apple Music: Ошибка: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=f"❌ Apple Music: Ошибка: {e}",
        )
    finally:
        stop_typing.set()
        typing_task.cancel()


async def _download_apple_album(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """
    Скачивает и отправляет все треки альбома Apple Music по очереди.

    Одно сервисное сообщение переиспользуется под прогресс: иначе на альбом
    из десятка треков в чат сыпались бы десятки служебных строк.
    """
    downloader = AppleMusicDownloader()
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Apple Music: получаю список треков...")

    album_info = await downloader.get_album_info(url)
    if not album_info or not album_info["tracks"]:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text="❌ Apple Music: не удалось получить список треков альбома.",
        )
        return

    tracks = album_info["tracks"]
    sent_count = 0
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context.bot, chat_id, stop_typing))
    try:
        for track in tracks:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text=(
                    f"⏳ {_md_escape(album_info['title'])}\n"
                    f"Трек {track['index']} из {len(tracks)}: {_md_escape(track['title'])}"
                ),
                parse_mode="Markdown",
            )

            audio_file, cover_file = await downloader.download_track(track["url"])
            if not audio_file:
                logger.warning(f"⚠️ Apple Music: трек «{track['title']}» не скачался, пропускаю")
                continue

            await process_and_send_audio(
                update, context, sent_message, audio_file, cover_file, url,
                "Apple Music", keep_status_message=True,
            )
            sent_count += 1
    except AppleMusicError as e:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text=e.user_message, parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"❌ Apple Music: Ошибка при скачивании альбома: {e}")
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        except Exception:
            pass

    if sent_count == 0:
        await context.bot.send_message(chat_id=chat_id, text="❌ Apple Music: не удалось скачать ни одного трека.")
    else:
        logger.info(f"✅ Apple Music: из альбома отправлено треков — {sent_count} из {len(tracks)}")


async def _download_spotify(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, track_index: Optional[int] = None):
    """
    Ссылка Spotify используется как источник метаданных: сам Spotify аудио
    не отдаёт. Файл берётся с Qobuz (Hi-Res), затем с Apple Music, затем с YouTube.
    """
    downloader = SpotifyDownloader()
    # Вызывается и из кнопок, где update.message отсутствует
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Spotify: получаю данные трека...")

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context.bot, chat_id, stop_typing))
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text="🎧 Spotify: ищу на Qobuz (Hi-Res), затем на Apple Music, затем на YouTube...",
        )

        audio_file, cover_file = await downloader.download_track(url, track_index=track_index)

        if audio_file:
            # В подписи называется реальный источник: файл пришёл не со Spotify
            source = downloader.last_source or "YouTube"
            await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url, source)
        else:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text="❌ Spotify: трек не найден ни на Qobuz, ни на Apple Music, ни на YouTube.",
            )
    except SpotifyError as e:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=e.user_message,
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.exception(f"❌ Spotify: Ошибка: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=f"❌ Spotify: Ошибка: {e}",
        )
    finally:
        stop_typing.set()
        typing_task.cancel()


async def _download_spotify_album(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """
    Скачивает и отправляет все треки альбома по очереди.

    Одно сервисное сообщение переиспользуется под прогресс: иначе на альбом
    из десятка треков в чат сыпались бы десятки служебных строк.
    """
    downloader = SpotifyDownloader()
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Spotify: получаю список треков...")

    album_info = downloader.get_album_info(url)
    if not album_info or not album_info["tracks"]:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text="❌ Spotify: не удалось получить список треков альбома.",
        )
        return

    tracks = album_info["tracks"]
    sent_count = 0
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context.bot, chat_id, stop_typing))
    try:
        for track in tracks:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text=(
                    f"⏳ {_md_escape(album_info['title'])}\n"
                    f"Трек {track['index']} из {len(tracks)}: {_md_escape(track['title'])}"
                ),
                parse_mode="Markdown",
            )

            audio_file, cover_file = await downloader.download_track_by_id(track["id"])
            if not audio_file:
                logger.warning(f"⚠️ Spotify: трек «{track['title']}» не найден нигде, пропускаю")
                continue

            await process_and_send_audio(
                update, context, sent_message, audio_file, cover_file, url,
                downloader.last_source or "Spotify", keep_status_message=True,
            )
            sent_count += 1
    except SpotifyError as e:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text=e.user_message, parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception(f"❌ Spotify: Ошибка при скачивании альбома: {e}")
    finally:
        stop_typing.set()
        typing_task.cancel()
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        except Exception:
            pass

    if sent_count == 0:
        await context.bot.send_message(chat_id=chat_id, text="❌ Spotify: не удалось скачать ни одного трека.")
    else:
        logger.info(f"✅ Spotify: из альбома отправлено треков — {sent_count} из {len(tracks)}")


async def process_and_send_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, sent_message, initial_audio_file: Path, initial_cover_file: Optional[Path], url_for_caption: str, source: str, keep_status_message: bool = False):
    file_manager = FileManager()
    files_to_delete = {initial_audio_file}
    if initial_cover_file: files_to_delete.add(initial_cover_file)
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id

    try:
        if not initial_audio_file or not initial_audio_file.exists():
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Аудиофайл не найден.")
            return

        if initial_cover_file and has_embedded_cover(initial_audio_file):
            logger.info("ℹ️ Обложка уже встроена в файл — повторное встраивание не нужно.")
        else:
            embed_cover_art(initial_audio_file, initial_cover_file)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="💿 Обработка файла...")
        size_mb = file_manager.get_file_size_mb(initial_audio_file)
        audio_file_to_send = initial_audio_file
        
        if size_mb > Config.MAX_FILE_SIZE_MB: 
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="🎧 Файл слишком большой. Конвертирую...")
            converted_file = convert_to_mp3(initial_audio_file)
            if converted_file:
                files_to_delete.add(converted_file)
                audio_file_to_send = converted_file
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Ошибка конвертации.")
                return

        track_details = _get_metadata_from_file(audio_file_to_send)
        if not track_details.get('title') or track_details.get('title') == 'N/A':
            track_details = _get_metadata_from_qobuz_path(audio_file_to_send)
        
        real_quality = file_manager.get_audio_quality(audio_file_to_send) or "N/A"
        if source == "Apple Music":
            # Для m4a mutagen показывает bits_per_sample=16 и получается
            # «16-bit / 44.1 kHz», что читается как lossless. На деле это AAC,
            # поэтому показываем реальный кодек и битрейт.
            real_quality = _apple_quality_label(audio_file_to_send) or real_quality
        custom_filename = f"{track_details.get('artist', 'Unknown')} - {track_details.get('title', 'Unknown')}{audio_file_to_send.suffix}"

        caption_text = _build_caption(track_details, real_quality, source, url_for_caption)

        # 1. ОТПРАВЛЯЕМ ОБЛОЖКУ С КРАСИВОЙ ПОДПИСЬЮ
        if initial_cover_file and initial_cover_file.exists():
            cover_to_send = prepare_cover_for_telegram(initial_cover_file)
            if cover_to_send:
                if cover_to_send != initial_cover_file:
                    files_to_delete.add(cover_to_send)
                with open(cover_to_send, 'rb') as img:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=img,
                        caption=caption_text,
                        parse_mode='Markdown'
                    )
            else:
                # Обложку не удалось ужать до лимита — отправляем только текст
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption_text,
                    parse_mode='Markdown'
                )
        else:
            # Если обложки нет, отправляем только текст
            await context.bot.send_message(
                chat_id=chat_id,
                text=caption_text,
                parse_mode='Markdown'
            )

        # 2. ОТПРАВЛЯЕМ АУДИОФАЙЛ
        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(
                chat_id=chat_id, 
                audio=f, 
                filename=custom_filename
            )
        
        # Удаляем сервисное сообщение, если вызывающий не переиспользует его
        # под прогресс (альбом скачивается в цикле)
        if not keep_status_message:
            await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
    finally:
        for f in files_to_delete: file_manager.safe_remove(f)


def _get_metadata_from_file(file_path: Path) -> dict:
    """
    Читает теги: ID3 (MP3), Vorbis (FLAC) и MP4-атомы (m4a от Apple Music).

    easy=True обязателен: без него mutagen отдаёт у m4a сырые имена атомов
    (©nam, ©ART, soal, sonm), а код ищет title/artist/album — в итоге все
    поля выходили пустыми, подпись показывала Unknown. Для MP3 и FLAC
    easy-режим возвращает ровно то же, что и раньше.
    """
    details = {}
    try:
        audio = mutagen.File(file_path, easy=True)
        if not audio: return {}
        details['artist'] = audio.get('artist', ['N/A'])[0]
        details['title'] = audio.get('title', ['N/A'])[0]
        details['album'] = audio.get('album', ['N/A'])[0]
        year = audio.get('date', []) or audio.get('TDRC', []) or ['N/A']
        details['year'] = re.sub(r'[^0-9]', '', str(year[0]))[:4] or 'N/A'
        return details
    except Exception: return {}


def _build_caption(track_details: dict, quality: str, source: str, url: str) -> str:
    """
    Собирает лаконичную подпись без эмодзи:

        *Трек*
        Артист

        Альбом · Год
        Качество · Источник

    Пустые поля и заглушки прошлых версий ('N/A', 'Unknown') опускаются,
    а все подставляемые значения экранируются — иначе символы вроде '_'
    в названии трека ломают разметку и Telegram отклоняет сообщение целиком.
    """
    placeholders = ('N/A', 'Unknown')

    title = track_details.get('title') or 'Без названия'
    artist = track_details.get('artist') or ''
    album = track_details.get('album') or ''
    year = track_details.get('year') or ''

    caption = f"*{_md_escape(title)}*"
    if artist and artist not in placeholders:
        caption += f"\n{_md_escape(artist)}"

    album_year = [p for p in (album, year) if p and p not in placeholders]
    if album_year:
        caption += "\n\n" + " · ".join(_md_escape(p) for p in album_year)

    quality_line = [p for p in (quality,) if p and p not in placeholders]
    safe_url = str(url).replace(")", "\\)")
    quality_line.append(f"[{_md_escape(source)}]({safe_url})")
    caption += "\n" + " · ".join(quality_line)

    return caption


def _apple_quality_label(audio_file: Path) -> Optional[str]:
    """Реальное качество файла Apple Music: кодек AAC и его битрейт."""
    try:
        audio = mutagen.File(audio_file)
        bitrate = getattr(audio.info, "bitrate", 0)
        if bitrate:
            return f"AAC {round(bitrate / 1000)} kbps"
    except Exception as e:
        logger.warning(f"⚠️ Не удалось определить качество {audio_file.name}: {e}")
    return None


def _get_metadata_from_qobuz_path(audio_file: Path) -> dict:
    try:
        original_name = Path(str(audio_file).replace(".mp3", ".flac")).name
        album_folder = audio_file.parent.name
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        details = {}
        details.update(zip(['artist', 'album', 'year'], match.groups()) if match else zip(['artist', 'album', 'year'], ["Unknown"]*3))
        details['title'] = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0]).strip()
        return details
    except Exception: return {}


async def handle_audio_recognition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    message = update.message
    audio_source = message.audio or message.voice
    if not audio_source: return
    sent_message = await message.reply_text("🔎 Пытаюсь распознать...")
    temp_file_path = None
    converted_file_path = None 
    try:
        file_obj = await audio_source.get_file()
        file_bytes = await file_obj.download_as_bytearray() 
        temp_file_path = Path(f"{file_obj.file_id}{Path(file_obj.file_path).suffix or '.ogg'}")
        temp_file_path.write_bytes(bytes(file_bytes))
        converted_file_path = temp_file_path.with_suffix(".mp3")
        subprocess.run(["ffmpeg", "-i", str(temp_file_path), "-vn", "-acodec", "libmp3lame", "-b:a", "192k", str(converted_file_path)], check=True, capture_output=True)
        
        recognizer = AudioRecognizer()
        track_info = recognizer.recognize(str(converted_file_path))
        if not track_info:
            await sent_message.edit_text("❌ Не удалось распознать.")
            return

        artist, title = track_info['artist'], track_info['title']
        await sent_message.edit_text(f"✅ `{artist} - {title}`. Ищу на Qobuz...", parse_mode='Markdown')
        
        downloader = QobuzDownloader()
        file_manager = FileManager()
        async def progress_callback(percent):
            try:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=sent_message.message_id, text=f"✅ `{artist} - {title}`\n💿 {file_manager.format_progress_bar(percent)}", parse_mode='Markdown')
            except Exception: pass

        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(_typing_loop(context.bot, update.effective_chat.id, stop_typing))
        try:
            audio_file, cover_file = await downloader.search_and_download_lucky(artist, title)
            if audio_file:
                await process_and_send_audio(update, context, sent_message, audio_file, cover_file, "https://qobuz.com", "Qobuz")
            else:
                await sent_message.edit_text("❌ Не найдено на Qobuz.")
        except QobuzAuthError:
            await sent_message.edit_text(_token_expired_message())
        finally:
            stop_typing.set()
            typing_task.cancel()
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await sent_message.edit_text("❌ Ошибка.")
    finally:
        if temp_file_path and temp_file_path.exists(): temp_file_path.unlink()
        if converted_file_path and converted_file_path.exists(): converted_file_path.unlink()
