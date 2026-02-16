from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from services.downloader import QobuzDownloader
from services.savify_downloader import SavifyDownloader 
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
import asyncio # Импорт нужен для asyncio.get_running_loop() и run_in_executor
from io import BytesIO # <-- ДОБАВЛЕНО для работы с байтами

logger = logging.getLogger(__name__)

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

QUALITY_HIERARCHY = {
    "HI-RES (Max)": 27,
    "HI-RES (<96kHz)": 7,
    "CD (16-bit)": 6,
    "MP3 (320 kbps)": 5,
}

# --- Команды Start/Help ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Я бот версии 2.0 и могу скачивать треки с Qobuz и Spotify. 🚀")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек (Qobuz или Spotify)\n"
        "Или просто отправь аудио для распознавания."
    )

# --- УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ЗАГРУЗКИ ---

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.args[0] if context.args else getattr(update.message, 'text', '').strip()
    if not url: return

    if re.search(r"qobuz\.com/", url):
        if "/album/" in url:
            await _show_qobuz_album_tracks(update, context, url)
        else:
            await _download_qobuz(update, context, url)
    elif re.search(r"spotify\.com/", url):
        await _download_spotify(update, context, url)
    else:
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на Qobuz или Spotify.")


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


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
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
    
    try:
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            base_text = f"💿 Qobuz: Качество {quality_name}\n"
            if track_index: base_text += f"🎵 Трек №{track_index}\n"
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"{base_text}⏳ Подготовка...")
            
            async def progress_callback(percent):
                progress_bar = file_manager.format_progress_bar(percent)
                try:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"{base_text}{progress_bar}")
                except Exception: pass

            audio_file, cover_file = await downloader.download_track(url, quality_id, progress_callback=progress_callback, track_index=track_index)
            if audio_file:
                await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url, "Qobuz")
                return 
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Qobuz: Не удалось скачать файл.")
    except Exception as e:
        logger.exception(f"❌ Qobuz: Ошибка: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Qobuz: Ошибка: {e}")


async def _download_spotify(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    downloader = SavifyDownloader()
    sent_message = await update.message.reply_text("⏳ Начинаю поиск на Spotify...")
    try:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=sent_message.message_id, text="💿 Spotify: Ищу и скачиваю...")
        audio_file, cover_file = await downloader.download_track(url)
        if audio_file:
            await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url, "Spotify")
        else:
            await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=sent_message.message_id, text="❌ Spotify: Не удалось скачать.")
    except Exception as e:
        logger.exception(f"❌ Spotify: Ошибка: {e}")
        await update.message.reply_text(f"❌ Spotify: Ошибка: {e}")


async def process_and_send_audio(update: Update, context: ContextTypes.DEFAULT_TYPE, sent_message, initial_audio_file: Path, initial_cover_file: Optional[Path], url_for_caption: str, source: str):
    file_manager = FileManager()
    files_to_delete = {initial_audio_file}
    if initial_cover_file: files_to_delete.add(initial_cover_file)
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id

    try:
        if not initial_audio_file or not initial_audio_file.exists():
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Аудиофайл не найден.")
            return

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
        custom_filename = f"{track_details.get('artist', 'Unknown')} - {track_details.get('title', 'Unknown')}{audio_file_to_send.suffix}"

        caption_text = (
            f"🎼 **{track_details.get('title', 'N/A')}**\n"
            f"👤 `{track_details.get('artist', 'N/A')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"📅 **Год:** {track_details.get('year', 'N/A')}\n"
            f"✨ **Качество:** {real_quality}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 [Скачано с {source}]({url_for_caption})"
        )

        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(chat_id=chat_id, audio=f, caption=caption_text, parse_mode='Markdown', filename=custom_filename)
        
        await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
    finally:
        for f in files_to_delete: file_manager.safe_remove(f)


def _get_metadata_from_file(file_path: Path) -> dict:
    details = {}
    try:
        audio = mutagen.File(file_path)
        if not audio: return {}
        details['artist'] = audio.get('artist', ['N/A'])[0]
        details['title'] = audio.get('title', ['N/A'])[0]
        details['album'] = audio.get('album', ['N/A'])[0]
        year = audio.get('date', []) or audio.get('TDRC', []) or ['N/A']
        details['year'] = re.sub(r'[^0-9]', '', str(year[0]))[:4]
        return details
    except Exception: return {}


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

        audio_file, cover_file = await downloader.search_and_download_lucky(artist, title, progress_callback=progress_callback)
        if audio_file:
            await process_and_send_audio(update, context, sent_message, audio_file, cover_file, "https://qobuz.com", "Qobuz")
        else:
            await sent_message.edit_text("❌ Не найдено на Qobuz.")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await sent_message.edit_text("❌ Ошибка.")
    finally:
        if temp_file_path and temp_file_path.exists(): temp_file_path.unlink()
        if converted_file_path and converted_file_path.exists(): converted_file_path.unlink()
