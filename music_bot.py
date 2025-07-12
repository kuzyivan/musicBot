import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
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

# Клавиатура
main_keyboard = ReplyKeyboardMarkup(
    [["/qobuz", "/track"], ["/download", "/help"]],
    resize_keyboard=True
)

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start от {user.id} ({user.username})")
    await update.message.reply_text(
        "🎶 Привет! Я KuzyMusicBot.\n"
        "Напиши /help для списка команд.",
        reply_markup=main_keyboard
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 Команды:\n"
        "/start — перезапуск\n"
        "/qobuz — информация о Qobuz\n"
        "/track — получить трек по ссылке\n"
        "/download — загрузить из Qobuz\n"
        "/help — справка"
    )

async def qobuz_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎧 Qobuz — это Hi-Res музыкальный сервис. Введи ссылку, и я попробую её скачать.")

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔗 Вставь ссылку на трек Qobuz. В будущем я скачаю его для тебя 😉")

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⬇️ Функция загрузки скоро будет доступна!")

# Ошибки
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ Упс! Что-то пошло не так.")

# Запуск
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
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("qobuz", qobuz_info))
    app.add_handler(CommandHandler("track", track_command))
    app.add_handler(CommandHandler("download", download_command))
    app.add_error_handler(error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()