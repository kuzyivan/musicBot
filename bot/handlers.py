from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging
import re

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 Привет! Я могу скачивать треки с Qobuz.\n"
        "Отправь ссылку на трек после команды /download"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек с Qobuz\n"
        "/help — список команд"
    )

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.effective_chat.id

    downloader = QobuzDownloader()
    file_manager = FileManager()

    try:
        await update.message.reply_text("⏳ Пробую скачать трек в лучшем качестве...")

        audio_file = None
        cover_file = None
        size = None

        for quality in ["6", "5", "3"]:
            audio_file, cover_file = await downloader.download_track(url, quality=quality)

            if not audio_file:
                continue  # Переход к следующему качеству, если не скачалось

            size = file_manager.get_file_size_mb(audio_file)

            if size <= 50:
                logger.info(f"✅ Успешно загружено в качестве {quality}, размер: {size:.2f} MB")
                break  # Файл подходит по размеру
            else:
                logger.info(f"⚠️ Качество {quality} слишком большое: {size:.2f} MB — пробуем ниже")
                file_manager.safe_remove(audio_file)
                file_manager.safe_remove(cover_file)
                await update.message.reply_text(f"⚠️ Качество {quality} слишком большое ({size:.1f} МБ), пробую ниже...")

        if not audio_file or size > 50:
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
            with open(audio_file, 'rb') as f:
                await context.bot.send_audio(chat_id, f, filename=custom_filename)

            if cover_file:
                with open(cover_file, 'rb') as img:
                    await context.bot.send_photo(chat_id, img)

            await update.message.reply_text("✅ Трек успешно отправлен!")

        finally:
            file_manager.safe_remove(audio_file)
            file_manager.safe_remove(cover_file)

    except Exception as e:
        logger.exception("Ошибка при загрузке трека")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")