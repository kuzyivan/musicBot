import os
import shlex
import asyncio
import logging
import datetime
import subprocess
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Параметры
BOT_TOKEN = os.getenv("BOT_TOKEN")
DOWNLOAD_DIR = os.path.expanduser("~/musicBot/Qobuz/Downloads")
VENV_PYTHON = "/opt/qobuz-env/bin/python"
QOBUZ_DL = "/opt/qobuz-env/bin/qobuz-dl"

# Очередь задач
download_queue = asyncio.Queue()

# Настройка логгера
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Прогресс-бар
def create_progress_bar(percent):
    total_blocks = 10
    filled_blocks = int(percent / (100 / total_blocks))
    bar = "█" * filled_blocks + "░" * (total_blocks - filled_blocks)
    return f"[{bar}]"

# Отправка трека пользователю
async def send_track(update: Update, release_id: str):
    folder = os.path.join(DOWNLOAD_DIR, os.listdir(DOWNLOAD_DIR)[0])  # берём первую папку
    logger.info(f"Ищем трек в папке: {folder}")

    for filename in os.listdir(folder):
        if filename.lower().endswith(".flac") or filename.lower().endswith(".mp3"):
            filepath = os.path.join(folder, filename)
            cover_path = os.path.join(folder, "cover.jpg")

            # Отправка файла
            with open(filepath, "rb") as audio_file:
                if os.path.exists(cover_path):
                    with open(cover_path, "rb") as thumb:
                        await update.message.reply_audio(audio=audio_file, thumbnail=thumb)
                else:
                    await update.message.reply_audio(audio=audio_file)

            logger.info(f"Отправлен файл: {filepath}")

            # Удаление папки
            subprocess.run(["rm", "-rf", folder])
            logger.info("Удалена папка после отправки")

            break

# Очередь загрузки
async def download_worker():
    while True:
        link, update = await download_queue.get()
        try:
            release_id = link.strip().split("/")[-1]
            cmd = f"{QOBUZ_DL} dl --no-db {shlex.quote(link)}"
            logger.info(f"Запуск команды: {cmd}")

            progress_msg = await update.message.reply_text("⏳ Загрузка началась...\n[░░░░░░░░░░] 0%")

            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=DOWNLOAD_DIR
            )

            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                decoded = line.decode().strip()
                logger.info(decoded)

                if "%" in decoded:
                    try:
                        percent_str = decoded.split()[-1].replace("%", "")
                        percent = int(float(percent_str))
                        bar = create_progress_bar(percent)
                        await progress_msg.edit_text(f"⬇️ Загрузка...\n{bar} {percent}%")
                    except Exception as e:
                        logger.warning(f"Не удалось распарсить строку: {decoded} — {e}")

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                await update.message.reply_text(f"❌ Ошибка загрузки:\n{stderr.decode()}")
                logger.error(stderr.decode())
            else:
                logger.info("Загрузка завершена")
                await progress_msg.edit_text("✅ Загрузка завершена!")
                await send_track(update, release_id)

        except Exception as e:
            logger.error(f"Ошибка при скачивании: {e}")
            await update.message.reply_text("❌ Произошла ошибка при загрузке трека.")
        finally:
            download_queue.task_done()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Отправь /download, а потом ссылку на трек Qobuz 🎧")

# Команда /download
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Жду ссылку на трек Qobuz...")

# Обработка сообщений
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "qobuz.com/track/" in update.message.text:
        await download_queue.put((update.message.text.strip(), update))
        await update.message.reply_text("🛰 Добавлено в очередь на загрузку...")
    else:
        await update.message.reply_text("Пожалуйста, пришли ссылку на трек Qobuz 🎶")

# Запуск бота
async def main():
    logger.info("🚀 KuzyMusicBot запускается...")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    asyncio.create_task(download_worker())

    logger.info(f"🤖 KuzyMusicBot запущен в {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"❗ Ошибка: {e}")