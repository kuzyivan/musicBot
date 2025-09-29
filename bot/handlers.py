from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Функция конвертации ---
def convert_to_mp3(file_path: Path) -> Path:
    mp3_path = file_path.with_suffix(".mp3")
    logger.info(f"Конвертация файла {file_path} в MP3...")
    try:
        subprocess.run(
            ["ffmpeg", "-i", str(file_path), "-b:a", "320k", "-vn", str(mp3_path)],
            check=True, capture_output=True,
        )
        logger.info(f"Файл успешно сконвертирован в {mp3_path}")
        return mp3_path
    except Exception as e:
        logger.error(f"Ошибка конвертации ffmpeg: {e}")
        return None

# --- Словарь качеств ---
QUALITY_HIERARCHY = {
    "HI-RES (Max)": 27,
    "CD (16-bit)": 6,
    "MP3 (320 kbps)": 5,
}

# --- ОБНОВЛЕННАЯ ФУНКЦИЯ START (БЕЗ СТИКЕРА) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение."""
    caption_text = "Бот создан для знакомства с музыкой в канале @sondamusic"
    await update.message.reply_text(caption_text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — приветствие\n/download <ссылка> — скачать трек")

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.args[0] if context.args else getattr(getattr(update, 'message', None), 'text', '').strip()
    if not url:
        await update.message.reply_text("❌ Пожалуйста, укажите ссылку на трек.")
        return

    chat_id = update.effective_chat.id
    if not re.match(r"https?://(www\.|open\.|play\.)?qobuz\.com/(.+)", url):
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на трек Qobuz.")
        return

    downloader = QobuzDownloader()
    file_manager = FileManager()
    
    audio_file_to_send = None
    cover_file_to_send = None
    files_to_delete = set()
    track_details = {}

    try:
        sent_message = await update.message.reply_text("⏳ Начинаю поиск...")
        
        for i, (quality_name, quality_id) in enumerate(QUALITY_HIERARCHY.items()):
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=sent_message.message_id,
                text=f"💿 Пробую скачать в качестве: {quality_name}..."
            )
            
            audio_file, cover_file = await downloader.download_track(url, quality_id)
            if cover_file: files_to_delete.add(cover_file)

            if not audio_file:
                logger.warning(f"Не удалось скачать в качестве {quality_name}.")
                continue

            files_to_delete.add(audio_file)
            size_mb = file_manager.get_file_size_mb(audio_file)
            
            if size_mb <= 48:
                audio_file_to_send = audio_file
                cover_file_to_send = cover_file
                track_details['quality_name'] = quality_name
                break
            else:
                is_last_attempt = (i == len(QUALITY_HIERARCHY) - 1)
                if is_last_attempt:
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=sent_message.message_id,
                        text=f"🎧 Файл все еще слишком большой ({size_mb:.2f} MB). Конвертирую в MP3..."
                    )
                    converted_file = convert_to_mp3(audio_file)
                    if converted_file:
                        files_to_delete.add(converted_file)
                        audio_file_to_send = converted_file
                        cover_file_to_send = cover_file
                        track_details['quality_name'] = "MP3 (320 kbps)"
                    break

        if not audio_file_to_send:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=sent_message.message_id, 
                text="❌ Не удалось скачать файл. Возможно, трек слишком длинный."
            )
            return

        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text="📤 Файл готов, начинается отправка в Telegram..."
        )

        # --- ИЗВЛЕКАЕМ ТОЧНОЕ КАЧЕСТВО ИЗ ФАЙЛА ---
        precise_quality = file_manager.get_audio_quality(audio_file_to_send)
        if precise_quality:
            track_details['quality_name'] = precise_quality
        # Если не удалось, останется старое значение из QUALITY_HIERARCHY

        original_name = Path(str(audio_file_to_send).replace(".mp3", ".flac")).name
        album_folder = audio_file_to_send.parent.name
        
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        if match:
            track_details['artist'], track_details['album'], track_details['year'] = map(str.strip, match.groups())
        else:
            track_details['artist'], track_details['album'], track_details['year'] = "Unknown", "Unknown", "0000"

        track_details['title'] = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0]).strip()
        ext = audio_file_to_send.suffix
        custom_filename = f"{track_details['artist']} - {track_details['title']} ({track_details['album']}, {track_details['year']}){ext}"
        
        caption_text = (
            f"🎤 **Артист:** {track_details.get('artist', 'N/A')}\n"
            f"🎵 **Трек:** {track_details.get('title', 'N/A')}\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"🗓️ **Год:** {track_details.get('year', 'N/A')}\n\n"
            f"✨ **Качество:** {track_details.get('quality_name', 'N/A')}"
        )
        
        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(
                chat_id=chat_id, 
                audio=f, 
                filename=custom_filename
            )

        if cover_file_to_send:
            with open(cover_file_to_send, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=img,
                    caption=caption_text,
                    parse_mode='Markdown'
                )
        
        await context.bot.delete_message(chat_id, sent_message.message_id)

    except Exception as e:
        logger.exception("Общая ошибка при обработке запроса")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")
    finally:
        logger.info("Очистка временных файлов...")
        for file_to_delete in files_to_delete:
            file_manager.safe_remove(file_to_delete)
        logger.info("Временные файлы удалены.")