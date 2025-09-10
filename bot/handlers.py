from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging
import re

logger = logging.getLogger(__name__)

# Словарь качеств для перебора: от лучшего к худшему
QUALITY_HIERARCHY = {
    "HI-RES (24-bit < 96kHz)": 7,
    "CD (16-bit)": 6,
    "MP3 (320 kbps)": 5,
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 Привет! Я могу скачивать треки с Qobuz.\n"
        "Отправь мне ссылку на трек или используй команду /download <ссылка>"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек с Qobuz\n"
        "/help — список команд"
    )

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = ""
    if context.args:
        url = context.args[0]
    elif update.message and update.message.text:
        url = update.message.text.strip()

    if not url:
        await update.message.reply_text("❌ Пожалуйста, укажите ссылку на трек.")
        return

    chat_id = update.effective_chat.id
    if not re.match(r"https?://(www\.|open\.|play\.)?qobuz\.com/(.+)", url):
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на трек Qobuz.")
        return

    downloader = QobuzDownloader()
    file_manager = FileManager()
    
    # Переменные для цикла
    audio_file_to_send = None
    cover_file_to_send = None
    
    try:
        sent_message = await update.message.reply_text("⏳ Начинаю поиск...")
        
        # --- Новая логика: цикл перебора качеств ---
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text=f"💿 Пробую скачать в качестве: {quality_name}..."
            )
            
            audio_file, cover_file = await downloader.download_track(url, quality_id)
            
            if not audio_file:
                logger.warning(f"Не удалось скачать в качестве {quality_name}. Пробую следующее.")
                continue

            size_mb = file_manager.get_file_size_mb(audio_file)
            
            if size_mb <= 48: # Оставляем запас до 50 МБ
                logger.info(f"Файл подходит по размеру ({size_mb:.2f} MB). Отправляем.")
                audio_file_to_send = audio_file
                cover_file_to_send = cover_file
                break # Выходим из цикла, так как нашли подходящий файл
            else:
                logger.warning(f"Файл слишком большой ({size_mb:.2f} MB). Пробую качество ниже.")
                file_manager.safe_remove(audio_file) # Удаляем слишком большой файл
                if cover_file:
                    file_manager.safe_remove(cover_file)
        
        # --- Конец цикла ---

        if not audio_file_to_send:
            logger.error(f"Не удалось скачать файл для {url} с подходящим размером.")
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=sent_message.message_id, 
                text="❌ Не удалось скачать файл. Возможно, даже в самом низком качестве он слишком большой для Telegram."
            )
            return

        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=sent_message.message_id,
            text="📤 Файл скачан, начинается отправка в Telegram..."
        )

        original_name = audio_file_to_send.name
        album_folder = audio_file_to_send.parent.name
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        if match:
            artist, album, year = match.groups()
        else:
            artist, album, year = "Unknown Artist", "Unknown Album", "0000"

        track_title = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0])
        ext = audio_file_to_send.suffix
        custom_filename = f"{artist.strip()} - {track_title.strip()} ({album.strip()}, {year.strip()}){ext}"
        
        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(chat_id, f, filename=custom_filename)

        if cover_file_to_send:
            with open(cover_file_to_send, 'rb') as img:
                await context.bot.send_photo(chat_id, img)
        
        await context.bot.delete_message(chat_id, sent_message.message_id)

    except Exception as e:
        logger.exception("Общая ошибка при обработке запроса")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")
    finally:
        # Удаляем временные файлы, если они остались
        if audio_file_to_send:
            file_manager.safe_remove(audio_file_to_send)
        if cover_file_to_send:
            file_manager.safe_remove(cover_file_to_send)
        logger.info("Временные файлы удалены.")