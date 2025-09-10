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
        "Отправь ссылку на трек после команды /download"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработана команда /help")
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек с Qobuz\n"
        "/help — список команд"
    )

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    logger.info(f"Получен запрос на скачивание: {url}")

    # Добавлена проверка URL
    if not re.match(r"https?://(www\.)?qobuz\.com/track/.+", url):
        logger.warning(f"Некорректная ссылка от пользователя {chat_id}: {url}")
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на трек Qobuz.")
        return

    downloader = QobuzDownloader()
    file_manager = FileManager()
    logger.debug(f"Инициализированы Downloader и FileManager для {url}")

    try:
        await update.message.reply_text("⏳ Пробую скачать трек в лучшем качестве...")
        logger.info("Начинается попытка скачивания...")

        audio_file = None
        cover_file = None
        size = None

        for quality in ["6", "5", "3"]:
            logger.info(f"Пробую качество: {quality}")
            audio_file, cover_file = await downloader.download_track(url, quality=quality)
            if audio_file:
                size = file_manager.get_file_size_mb(audio_file)
                logger.info(f"Файл успешно скачан, размер: {size:.2f} MB")
                break
            else:
                logger.warning(f"Не удалось скачать в качестве {quality}")

        if not audio_file or size > 50:
            logger.error(f"Не удалось найти подходящий файл для {url}. Последний размер: {size:.2f} MB")
            await update.message.reply_text("❌ Не удалось получить файл подходящего размера.")
            return

        # --- Формируем красивое имя файла ---
        original_name = audio_file.name
        album_folder = audio_file.parent.name

        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        if match:
            artist = match.group("artist").strip()
            album = match.group("album").strip()
            year = match.group("year").strip()
        else:
            artist = "Unknown"
            album = "Unknown"
            year = "0000"

        track_title = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0])
        ext = audio_file.suffix
        custom_filename = f"{artist} - {track_title} ({album}, {year}){ext}"
        # ------------------------------------
        
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