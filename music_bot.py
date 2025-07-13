import os
import glob
import logging
import subprocess
import asyncio
from datetime import datetime
from queue import Queue

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

from dotenv import load_dotenv
load_dotenv()

# Переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
QOBUZ_DL = "/opt/qobuz-env/bin/qobuz-dl"
DOWNLOAD_DIR = os.path.expanduser("~/musicBot/Qobuz/Downloads")

WAIT_FOR_LINK = range(1)
download_queue = Queue()
downloading = False

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(f"🤖 KuzyMusicBot запущен\n🕒 {now}")

# /download
async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ Укажи ссылку на трек. Пример:\nhttps://open.qobuz.com/track/12345")
    return WAIT_FOR_LINK

# Обработка ссылки
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    chat_id = update.effective_chat.id

    if not link.startswith("https://open.qobuz.com/track/"):
        await context.bot.send_message(chat_id=chat_id, text="❌ Неверная ссылка. Попробуй ещё раз.")
        return WAIT_FOR_LINK

    download_queue.put((chat_id, link))
    await context.bot.send_message(chat_id=chat_id, text="📥 Трек добавлен в очередь на загрузку.")
    asyncio.create_task(process_queue(context))
    return ConversationHandler.END

# Загрузка
async def process_queue(context: ContextTypes.DEFAULT_TYPE):
    global downloading
    if downloading or download_queue.empty():
        return
    downloading = True

    while not download_queue.empty():
        chat_id, link = download_queue.get()
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⬇️ Начинаю загрузку трека:\n{link}")
            logger.info(f"Загружаем {link}...")

            subprocess.run([QOBUZ_DL, "dl", "--no-db", link], check=True)

            flacs = glob.glob(f"{DOWNLOAD_DIR}/**/*.flac", recursive=True)
            if not flacs:
                await context.bot.send_message(chat_id=chat_id, text="❌ Не найден файл .flac")
                continue

            audio = flacs[0]
            cover = os.path.join(os.path.dirname(audio), "cover.jpg")

            with open(audio, "rb") as f:
                await context.bot.send_audio(chat_id=chat_id, audio=f)

            if os.path.exists(cover):
                with open(cover, "rb") as f:
                    await context.bot.send_photo(chat_id=chat_id, photo=f)

            os.remove(audio)
            if os.path.exists(cover):
                os.remove(cover)

            logger.info(f"✅ Отправлен и удалён: {audio}")
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка при загрузке:\n{e}")

    downloading = False

# Запуск
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("download", download_command)],
        states={WAIT_FOR_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)]},
        fallbacks=[],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)

    logger.info("🚀 KuzyMusicBot запускается...")
    app.run_polling()

if __name__ == "__main__":
    main()