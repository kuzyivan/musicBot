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

# --- Вспомогательные функции (без изменений) ---

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
        # Если не удалось спарсить, просто пробуем скачать всё (старое поведение)
        await sent_message.edit_text("⚠️ Не удалось получить список треков. Начинаю скачивание всего релиза...")
        await _download_qobuz(update, context, url)
        return

    text = f"💿 **{album_info['artist']} — {album_info['title']}**\n\nВыберите трек для скачивания:"
    
    keyboard = []
    # Группируем кнопки по 2 в ряд
    current_row = []
    for track in album_info['tracks']:
        # callback_data имеет формат: "qdl:index:url"
        # Ограничиваем длину URL, если нужно, или используем ID
        callback_data = f"qdl:{track['index']}:{url}"
        # Telegram ограничивает размер callback_data (64 байта). 
        # Если URL длинный, мы сохраним его в context.user_data
        
        button = InlineKeyboardButton(f"{track['index']}. {track['title']}", callback_data=f"qdl:{track['index']}")
        current_row.append(button)
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)
    
    # Кнопка "Скачать всё"
    keyboard.append([InlineKeyboardButton("📥 Скачать весь альбом", callback_data="qdl:all")])
    
    # Сохраняем URL в данных пользователя
    context.user_data['last_album_url'] = url

    reply_markup = InlineKeyboardMarkup(keyboard)
    await sent_message.edit_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на Inline-кнопки."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith("qdl:"):
        return

    url = context.user_data.get('last_album_url')
    if not url:
        await query.edit_message_text("❌ Ошибка: ссылка потеряна. Отправьте её заново.")
        return

    action = data.split(":")[1]
    
    if action == "all":
        # Скачиваем весь альбом
        await query.edit_message_text("⏳ Начинаю скачивание всего альбома...")
        await _download_qobuz(update, context, url)
    else:
        # Скачиваем конкретный трек
        track_index = int(action)
        await query.edit_message_text(f"⏳ Начинаю скачивание трека №{track_index}...")
        await _download_qobuz(update, context, url, track_index=track_index)


async def _download_qobuz(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, track_index: Optional[int] = None):
    """Логика скачивания с Qobuz."""
    downloader = QobuzDownloader()
    file_manager = FileManager()
    
    # Если это вызов из callback, update может быть другим
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id
    
    sent_message = await context.bot.send_message(chat_id=chat_id, text="⏳ Подготовка к скачиванию...")
    
    try:
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            base_text = f"💿 Qobuz: Качество {quality_name}\n"
            if track_index:
                base_text += f"🎵 Трек №{track_index}\n"
                
            await context.bot.edit_message_text(
                chat_id=chat_id, 
                message_id=sent_message.message_id, 
                text=f"{base_text}⏳ Подготовка..."
            )
            
            async def progress_callback(percent):
                progress_bar = file_manager.format_progress_bar(percent)
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=sent_message.message_id,
                        text=f"{base_text}{progress_bar}"
                    )
                except Exception:
                    pass

            audio_file, cover_file = await downloader.download_track(
                url, quality_id, progress_callback=progress_callback, track_index=track_index
            )
            
            if audio_file:
                await process_and_send_audio(
                    update, context, sent_message, 
                    audio_file, cover_file, 
                    url_for_caption=url, source="Qobuz"
                )
                return 
            
            logger.warning(f"⚠️ Qobuz: Файл для качества '{quality_name}' не был скачан. Пробую следующее.")

        await context.bot.edit_message_text(
            chat_id=chat_id, 
            message_id=sent_message.message_id, 
            text="❌ Qobuz: Не удалось скачать файл ни в одном из доступных качеств."
        )
    
    except Exception as e:
        logger.exception(f"❌ Qobuz: Общая ошибка при обработке запроса: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Qobuz: Произошла ошибка: {e}")


async def _download_spotify(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    downloader = SavifyDownloader()
    sent_message = await update.message.reply_text("⏳ Начинаю поиск на Spotify...")

    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, 
            message_id=sent_message.message_id, 
            text=f"💿 Spotify: Ищу трек и скачиваю (через YouTube)..."
        )
        
        audio_file, cover_file = await downloader.download_track(url)
        
        if audio_file:
            await process_and_send_audio(
                update, context, sent_message, 
                audio_file, cover_file, 
                url_for_caption=url, source="Spotify"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, 
                message_id=sent_message.message_id, 
                text="❌ Spotify: Не удалось скачать файл. Возможно, он не найден на YouTube."
            )
    except Exception as e:
        logger.exception(f"❌ Spotify: Общая ошибка при обработке запроса: {e}")
        await update.message.reply_text(f"❌ Spotify: Произошла ошибка: {e}")


async def process_and_send_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sent_message,
    initial_audio_file: Path,
    initial_cover_file: Optional[Path],
    url_for_caption: str,
    source: str 
):
    file_manager = FileManager()
    files_to_delete = set()
    
    # Определяем chat_id (может быть из сообщения или callback)
    target_update = update.callback_query if update.callback_query else update
    chat_id = target_update.message.chat_id

    try:
        if not initial_audio_file or not initial_audio_file.exists():
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Не удалось найти скачанный аудиофайл.")
            return

        files_to_delete.add(initial_audio_file)
        if initial_cover_file:
            files_to_delete.add(initial_cover_file)

        embed_cover_art(initial_audio_file, initial_cover_file)
        
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="💿 Файл скачан, проверяю размер...")
        size_mb = file_manager.get_file_size_mb(initial_audio_file)
        
        audio_file_to_send = initial_audio_file
        
        if size_mb > Config.MAX_FILE_SIZE_MB: 
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"🎧 Файл слишком большой ({size_mb:.2f} MB). Конвертирую в MP3...")
            converted_file = convert_to_mp3(initial_audio_file)
            if converted_file:
                files_to_delete.add(converted_file)
                audio_file_to_send = converted_file
            else:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Файл слишком большой, и не удалось его сконвертировать.")
                return

        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="📤 Файл готов, начинается отправка...")

        track_details = _get_metadata_from_file(audio_file_to_send)
        if not track_details.get('title') or track_details.get('title') == 'N/A':
            track_details = _get_metadata_from_qobuz_path(audio_file_to_send)
        
        real_quality = file_manager.get_audio_quality(audio_file_to_send) or "N/A"
        if "MP3" in real_quality and source == "Spotify":
             real_quality = "MP3 (до 320 kbps)"

        ext = audio_file_to_send.suffix
        custom_filename = f"{track_details.get('artist', 'Unknown')} - {track_details.get('title', 'Unknown')}{ext}"

        caption_text = (
            f"🎤 **Артист:** `{track_details.get('artist', 'N/A')}`\n"
            f"🎵 **Трек:** `{track_details.get('title', 'N/A')}`\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"🗓️ **Год:** {track_details.get('year', 'N/A')}\n\n"
            f"✨ **Качество:** {real_quality}\n\n"
            f"Скачано с [{source}]({url_for_caption})"
        )

        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(chat_id=chat_id, audio=f, filename=custom_filename)
        
        if initial_cover_file and initial_cover_file.exists():
            with open(initial_cover_file, 'rb') as img:
                await context.bot.send_photo(chat_id=chat_id, photo=img, caption=caption_text, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption_text, parse_mode='Markdown')
        
        await context.bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)

    finally:
        for file_to_delete in files_to_delete:
            file_manager.safe_remove(file_to_delete)


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

    sent_message = await message.reply_text("🔎 Получил аудио, пытаюсь распознать...")
    temp_file_path = None
    converted_file_path = None 
    
    try:
        file_obj = await audio_source.get_file()
        await sent_message.edit_text("⏳ Скачиваю аудио...")
        file_bytes = await file_obj.download_as_bytearray() 
        
        temp_file_path = Path(f"{file_obj.file_id}{Path(file_obj.file_path).suffix or '.ogg'}")
        loop = context.application.loop 
        await loop.run_in_executor(None, temp_file_path.write_bytes, bytes(file_bytes))
        
        converted_file_path = temp_file_path.with_suffix(".mp3")
        await sent_message.edit_text("⏳ Конвертирую аудио для распознавания...")
        
        command = ["ffmpeg", "-i", str(temp_file_path), "-vn", "-acodec", "libmp3lame", "-b:a", "192k", str(converted_file_path)]
        await loop.run_in_executor(None, subprocess.run, command, {"check": True, "capture_output": True})
        
        recognizer = AudioRecognizer()
        track_info = recognizer.recognize(str(converted_file_path))
        
        if not track_info:
            await sent_message.edit_text("❌ К сожалению, не удалось распознать этот трек.")
            return

        artist, title = track_info['artist'], track_info['title']
        base_text = f"✅ Распознано: `{artist} - {title}`\n"
        await sent_message.edit_text(f"{base_text}🔎 Ищу на Qobuz...", parse_mode='Markdown')
        
        downloader = QobuzDownloader()
        file_manager = FileManager()

        async def progress_callback(percent):
            progress_bar = file_manager.format_progress_bar(percent)
            try:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=sent_message.message_id, text=f"{base_text}💿 Скачиваю: {progress_bar}", parse_mode='Markdown')
            except Exception: pass

        audio_file, cover_file = await downloader.search_and_download_lucky(artist, title, progress_callback=progress_callback)
        
        if not audio_file:
            await sent_message.edit_text(f"❌ Трек `{artist} - {title}` не найден на Qobuz.", parse_mode='Markdown')
            return

        await process_and_send_audio(update, context, sent_message, audio_file, cover_file, "https://qobuz.com", source="Qobuz (via Shazam)")

    except Exception as e:
        logger.error(f"❌ Ошибка в процессе распознавания: {e}")
        await sent_message.edit_text("❌ Произошла непредвиденная ошибка во время распознавания.")
    finally:
        if temp_file_path and temp_file_path.exists(): temp_file_path.unlink()
        if converted_file_path and converted_file_path.exists(): converted_file_path.unlink()
