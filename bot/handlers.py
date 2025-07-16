from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging

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
        await update.message.reply_text("⏳ Загружаю трек...")

        audio_file, cover_file = await downloader.download_track(url)

        if not audio_file:
            await update.message.reply_text("❌ Не удалось загрузить трек.")
            return

        size = file_manager.get_file_size_mb(audio_file)

        try:
            with open(audio_file, 'rb') as f:
                if size <= 50:
                    await context.bot.send_audio(chat_id, f)
                elif size <= Config.MAX_FILE_SIZE_MB:
                    await context.bot.send_document(chat_id, f, filename=audio_file.name)
                else:
                    await update.message.reply_text("❌ Файл слишком большой для Telegram (>2GB).")
                    return

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