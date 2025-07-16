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

# Рекурсивный поиск аудиофайлов
def find_audio_files(directory):
    found_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith((".flac", ".mp3")):
                full_path = os.path.join(root, file)
                logger.info(f"🔍 Найден файл: {full_path}")
                found_files.append(full_path)
    return found_files

# Воркер загрузки
async def download_worker():
    while True:
        update, context, url = await download_queue.get()
        chat_id = update.effective_chat.id

        try:
            temp_id = uuid4().hex
            logger.info(f"🔻 Начинаем загрузку: {url}")
            await context.bot.send_message(chat_id, f"🚀 Начинаю загрузку трека:\n{url}")

            # Переход в папку загрузки
            os.chdir(DOWNLOAD_DIR)

            # Команда загрузки с пониженным качеством
            command = [
                QOBUZ_DL, "dl", url,
                "--no-db",
                "--quality", "6"
            ]
            process = Popen(command, stdout=PIPE, stderr=PIPE)
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

            # Поиск аудиофайлов
            downloaded_files = find_audio_files(DOWNLOAD_DIR)
            if not downloaded_files:
                await context.bot.send_message(chat_id, "❌ Загрузка не завершилась корректно.")
                continue

            track_file = downloaded_files[0]
            cover_file = os.path.join(os.path.dirname(track_file), "cover.jpg")
            cover_file = cover_file if os.path.exists(cover_file) else None

            # Проверка размера
            file_size = os.path.getsize(track_file)
            size_mb = round(file_size / 1024 / 1024, 2)

            try:
                if file_size <= 50 * 1024 * 1024:
                    logger.info(f"📤 Отправка трека как audio ({size_mb} MB)")
                    await context.bot.send_audio(chat_id=chat_id, audio=open(track_file, "rb"))
                elif file_size <= 2 * 1024 * 1024 * 1024:
                    logger.info(f"📤 Отправка трека как document ({size_mb} MB)")
                    await context.bot.send_document(chat_id=chat_id, document=open(track_file, "rb"), filename=os.path.basename(track_file))
                else:
                    await context.bot.send_message(chat_id, "❌ Файл слишком большой для отправки через Telegram (> 2 ГБ).")
                    logger.warning(f"❗ Файл слишком большой: {track_file} ({size_mb} MB)")
                    continue
            except Exception as send_err:
                logger.exception("🚫 Ошибка при отправке файла")
                await context.bot.send_message(chat_id, "❌ Не удалось отправить файл. Возможно, он слишком большой или Telegram временно недоступен.")

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
if __name__ == "__main__":
    logger.info("🚀 KuzyMusicBot запускается...")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("download", download_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    async def on_startup(app):
        asyncio.create_task(download_worker())
        logger.info("🤖 KuzyMusicBot запущен и готов к работе")

    application.post_init = on_startup
    application.run_polling()