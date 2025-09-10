from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging
import re

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработана команда /start")
    await update.message.reply_text(
        "🎵 Привет! Я могу скачивать треки с Qobuz.\n"
        "Отправь мне ссылку на трек или используй команду /download <ссылка>"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработана команда /help")
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
    logger.info(f"Получен запрос на скачивание: {url}")

    if not re.match(r"https?://(www\.|open\.)?qobuz\.com/track/.+", url):
        logger.warning(f"Некорректная ссылка от пользователя {chat_id}: {url}")
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на трек Qobuz.")
        return

    downloader = QobuzDownloader()
    file_manager = FileManager()

    try:
        await update.message.reply_text("⏳ Пробую скачать трек...")
        logger.info("Начинается попытка скачивания...")

        audio_file = None
        cover_file = None
        size = None

        for quality in ["6", "5", "3"]:
            logger.info(f"Пробую качество: {quality}")
            audio_file, cover_file = await downloader.download_track(url, quality=quality)
            if audio_file:
                size = file_manager.get_file_size_mb(audio_file)
                if size <= 50:
                    logger.info(f"Файл успешно скачан, размер: {size:.2f} MB. Подходит.")
                    break
                else:
                    logger.warning(f"Файл скачан, но слишком большой ({size:.2f} MB). Пробую ниже качество.")
                    file_manager.safe_remove(audio_file) # Удаляем слишком большой файл
                    audio_file = None # Сбрасываем, чтобы цикл продолжился
            else:
                logger.warning(f"Не удалось скачать в качестве {quality}")
        
        # --- ИСПРАВЛЕНА ЛОГИКА ПРОВЕРКИ И ЛОГИРОВАНИЯ ---
        if not audio_file:
            logger.error(f"Не удалось скачать файл для {url} ни в одном из качеств.")
            await update.message.reply_text("❌ Не удалось скачать файл. Попробуйте другую ссылку.")
            return

        original_name = audio_file.name
        album_folder = audio_file.parent.name

        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        if match:
            artist = match.group("artist").strip()
            album = match.group("album").strip()
            year = match.group("year").strip()
        else:
            artist = "Unknown Artist"
            album = "Unknown Album"
            year = "0000"

        track_title = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0])
        ext = audio_file.suffix
        custom_filename = f"{artist} - {track_title} ({album}, {year}){ext}"
        
        try:
            logger.info("Начинается отправка файла в Telegram.")
            with open(audio_file, 'rb') as f:
                await context.bot.send_audio(chat_id, f, filename=custom_filename)

            if cover_file:
                with open(cover_file, 'rb') as img:
                    await context.bot.send_photo(chat_id, img)
            logger.info("Файл успешно отправлен.")

        finally:
            file_manager.safe_remove(audio_file)
            file_manager.safe_remove(cover_file)
            logger.info("Временные файлы удалены.")

    except Exception as e:
        logger.exception("Общая ошибка при обработке запроса")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")