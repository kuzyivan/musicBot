from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from services.recognizer import AudioRecognizer
from config import Config
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional
import shutil
import time
from collections import defaultdict
from functools import wraps

logger = logging.getLogger(__name__)

# --- БЛОК ДЛЯ ОГРАНИЧЕНИЯ ЗАПРОСОВ (RATE LIMIT) ---
USER_TIMESTAMPS = defaultdict(float)
COOLDOWN_SECONDS = 30 # Разрешаем один запрос раз в 30 секунд

def rate_limit(cooldown: int):
    """Декоратор для ограничения частоты вызова функции."""
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            current_time = time.time()
            
            if current_time - USER_TIMESTAMPS[user_id] < cooldown:
                # Отвечаем только на сообщения с текстом или аудио, чтобы не спамить в ответ на редактирование
                if update.message:
                    await update.message.reply_text(f"⏳ Пожалуйста, подождите {cooldown} секунд перед следующим запросом.")
                return
            
            USER_TIMESTAMPS[user_id] = current_time
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
# --- КОНЕЦ БЛОКА ---


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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Я бот версии 2.0 и могу скачивать треки с Qobuz. 🚀")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — приветствие\n/download <ссылка> — скачать трек\nИли просто отправь аудио для распознавания.")

async def process_and_send_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sent_message,
    initial_audio_file: Path,
    initial_cover_file: Optional[Path],
    url_for_caption: str
):
    """
    Обрабатывает скачанный файл (проверяет размер, конвертирует) и отправляет его.
    """
    file_manager = FileManager()
    files_to_delete = set()
    track_details = {}

    try:
        if not initial_audio_file or not initial_audio_file.exists():
            await sent_message.edit_text("❌ Не удалось найти скачанный аудиофайл.")
            return

        files_to_delete.add(initial_audio_file)
        if initial_cover_file:
            files_to_delete.add(initial_cover_file)

        embed_cover_art(initial_audio_file, initial_cover_file)
        
        await sent_message.edit_text("💿 Файл скачан, проверяю размер...")
        size_mb = file_manager.get_file_size_mb(initial_audio_file)
        logger.info(f"ℹ️ Проверка файла: Размер = {size_mb:.2f} MB")
        
        audio_file_to_send = initial_audio_file
        if size_mb > 48:
            await sent_message.edit_text(f"🎧 Файл слишком большой ({size_mb:.2f} MB). Конвертирую в MP3...")
            converted_file = convert_to_mp3(initial_audio_file)
            if converted_file:
                files_to_delete.add(converted_file)
                audio_file_to_send = converted_file
            else:
                logger.error("❌ Конвертация в MP3 не удалась. Отправка невозможна.")
                await sent_message.edit_text("❌ Файл слишком большой, и не удалось его сконвертировать.")
                return

        await sent_message.edit_text("📤 Файл готов, начинается отправка...")

        original_name = Path(str(audio_file_to_send).replace(".mp3", ".flac")).name
        album_folder = audio_file_to_send.parent.name
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        track_details.update(zip(['artist', 'album', 'year'], map(str.strip, match.groups())) if match else zip(['artist', 'album', 'year'], ["Unknown"]*3))
        track_details['title'] = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0]).strip()

        ext = audio_file_to_send.suffix
        custom_filename = f"{track_details['artist']} - {track_details['title']} ({track_details['album']}, {track_details['year']}){ext}"

        quality_tech_info_match = re.search(r"\[(.*?)\]", album_folder)
        real_quality = quality_tech_info_match.group(1).replace('B', '-bit').replace('k', ' k') if quality_tech_info_match else "MP3 (320 kbps)"

        caption_text = (
            f"🎤 **Артист:** `{track_details.get('artist', 'N/A')}`\n"
            f"🎵 **Трек:** `{track_details.get('title', 'N/A')}`\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"🗓️ **Год:** {track_details.get('year', 'N/A')}\n\n"
            f"✨ **Качество:** {real_quality}\n\n"
            f"Скачано с [Qobuz]({url_for_caption})"
        )

        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(chat_id=update.effective_chat.id, audio=f, filename=custom_filename)

        if initial_cover_file and initial_cover_file.exists():
            with open(initial_cover_file, 'rb') as img:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=img, caption=caption_text, parse_mode='Markdown')

        await sent_message.delete()
    finally:
        logger.info("🗑️ Очистка временных файлов после отправки...")
        for file_to_delete in files_to_delete:
            file_manager.safe_remove(file_to_delete)
        logger.info("✅ Временные файлы удалены.")

@rate_limit(COOLDOWN_SECONDS)
async def handle_audio_recognition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    audio_source = message.audio or message.voice
    if not audio_source: return

    sent_message = await message.reply_text("🔎 Получил аудио, пытаюсь распознать...")
    temp_file_path = None
    try:
        temp_audio_file = await audio_source.get_file()
        temp_file_path = Path(f"{temp_audio_file.file_id}{Path(temp_audio_file.file_path).suffix or '.ogg'}")
        await temp_audio_file.download_to_drive(temp_file_path)
        
        recognizer = AudioRecognizer()
        track_info = recognizer.recognize(str(temp_file_path))
        
        if not track_info:
            await sent_message.edit_text("❌ К сожалению, не удалось распознать этот трек.")
            return

        artist, title = track_info['artist'], track_info['title']
        await sent_message.edit_text(f"✅ Распознано: `{artist} - {title}`. Ищу и скачиваю с Qobuz...", parse_mode='Markdown')
        
        downloader = QobuzDownloader()
        audio_file, cover_file = downloader.search_and_download_lucky(artist, title)
        
        if not audio_file:
            await sent_message.edit_text(f"❌ Трек `{artist} - {title}` не найден на Qobuz.", parse_mode='Markdown')
            return

        fake_url = "https://qobuz.com"
        await process_and_send_audio(update, context, sent_message, audio_file, cover_file, fake_url)

    except Exception as e:
        logger.error(f"❌ Ошибка в процессе распознавания: {e}")
        if sent_message:
            await sent_message.edit_text("❌ Произошла непредвиденная ошибка во время распознавания.")
    finally:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()

@rate_limit(COOLDOWN_SECONDS)
async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.args[0] if context.args else getattr(getattr(update, 'message', None), 'text', '').strip()
    if not url: return

    chat_id = update.effective_chat.id
    if not re.match(r"https?://(www\.|open\.|play\.)?qobuz\.com/(.+)", url):
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на трек Qobuz.")
        return

    downloader = QobuzDownloader()
    
    sent_message = await update.message.reply_text("⏳ Начинаю поиск...")
    
    try:
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"💿 Пробую скачать в качестве: {quality_name}...")
            
            audio_file, cover_file = await downloader.download_track(url, quality_id)
            
            if audio_file:
                await process_and_send_audio(update, context, sent_message, audio_file, cover_file, url)
                return 
            
            logger.warning(f"⚠️ Файл для качества '{quality_name}' не был скачан. Пробую следующее.")

        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Не удалось скачать файл ни в одном из доступных качеств.")
    
    except Exception as e:
        logger.exception(f"❌ Общая ошибка при обработке запроса: {e}")
        if sent_message:
            await sent_message.edit_text(f"❌ Произошла ошибка: {e}")