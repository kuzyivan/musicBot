import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
from subprocess import Popen, PIPE
from uuid import uuid4
from threading import Lock

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Пути
VENV_PYTHON = "/opt/qobuz-env/bin/python"
QOBUZ_DL = "/opt/qobuz-env/bin/qobuz-dl"
DOWNLOAD_DIR = "/root/musicBot/Qobuz/Downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Очередь и блокировка
download_queue = asyncio.Queue()
download_lock = Lock()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Отправь ссылку на трек Qobuz после команды /download")

# Команда /download
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Отправь ссылку на трек Qobuz одним сообщением")

# Обработка сообщений
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "qobuz.com/track/" in text:
        await download_queue.put((update, context, text))
        await update.message.reply_text("⏳ Трек добавлен в очередь загрузки... 🌀")
    else:
        await update.message.reply_text("❌ Это не ссылка на трек Qobuz!")

# Воркер загрузки
async def download_worker():
    while True:
        update, context, url = await download_queue.get()
        chat_id = update.effective_chat.id

        try:
            temp_id = uuid4().hex
            logger.info(f"🔻 Начинаем загрузку: {url}")
            await context.bot.send_message(chat_id, f"🚀 Начинаю загрузку трека:\n{url}")

            # Запуск qobuz-dl
            command = [QOBUZ_DL, "dl", url, "--no-db"]
            process = Popen(command, stdout=PIPE, stderr=PIPE, cwd=DOWNLOAD_DIR)
            stdout, stderr = process.communicate()

            stdout_decoded = stdout.decode().strip()
            stderr_decoded = stderr.decode().strip()

            if stdout_decoded:
                logger.info(stdout_decoded)
            if stderr_decoded:
                if "Error" in stderr_decoded or "Exception" in stderr_decoded:
                    logger.error(stderr_decoded)
                else:
                    logger.info(stderr_decoded)

            # Поиск загруженных треков
            downloaded_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".flac") or f.endswith(".mp3")]
            if not downloaded_files:
                await context.bot.send_message(chat_id, "❌ Не удалось найти загруженный файл.")
                continue

            track_file = os.path.join(DOWNLOAD_DIR, downloaded_files[0])
            cover_file = os.path.join(DOWNLOAD_DIR, "cover.jpg") if os.path.exists(os.path.join(DOWNLOAD_DIR, "cover.jpg")) else None

            # Отправка
            await context.bot.send_audio(chat_id=chat_id, audio=open(track_file, "rb"))
            if cover_file:
                await context.bot.send_photo(chat_id=chat_id, photo=open(cover_file, "rb"))

            # Удаление
            os.remove(track_file)
            if cover_file:
                os.remove(cover_file)

            await context.bot.send_message(chat_id, "✅ Готово! Трек отправлен и удалён с сервера.")

        except Exception as e:
            logger.exception("❗ Ошибка при загрузке трека")
            await context.bot.send_message(chat_id, f"❗ Ошибка при загрузке: {str(e)}")

        finally:
            download_queue.task_done()

# Основной запуск
async def main():
    logger.info("🚀 KuzyMusicBot запускается...")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Старт воркера
    asyncio.create_task(download_worker())

    logger.info("🤖 KuzyMusicBot запущен и готов к работе")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())