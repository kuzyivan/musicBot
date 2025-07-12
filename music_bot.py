import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Загрузка .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("music_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start от {user.id} ({user.username})")
    await update.message.reply_text("🎶 Привет! Я KuzyMusicBot. Напиши команду, и я постараюсь помочь!")

# Запуск бота
async def post_init(app):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"🤖 KuzyMusicBot запущен в {now}")
    if ADMIN_USER_ID:
        try:
            await app.bot.send_message(chat_id=ADMIN_USER_ID, text=f"🤖 KuzyMusicBot запущен\n🕒 {now}")
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение админу: {e}")

def main():
    logger.info("🚀 KuzyMusicBot запускается...")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))

    app.run_polling()

if __name__ == "__main__":
    main()
    
