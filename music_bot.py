import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
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


# --- Команды бота --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start от {user.id} ({user.username})")
    keyboard = [["/help", "/qobuz"], ["/track", "/download"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "🎶 Привет! Я KuzyMusicBot — помощник по скачиванию треков с Qobuz.\nНапиши /help, чтобы увидеть команды.",
        reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 Доступные команды:\n"
        "/start — приветствие\n"
        "/help — помощь\n"
        "/qobuz — о возможностях\n"
        "/track <ссылка> — инфо о треке\n"
        "/download <ссылка> — скачать трек"
    )


async def qobuz_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔊 Я умею скачивать треки с Qobuz в высоком качестве (до 24-bit / 96kHz), "
        "используя прямые ссылки. Просто пришли мне ссылку через /track или /download."
    )


async def track_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Укажи ссылку на трек после команды. Пример: /track https://open.qobuz.com/track/12345")
        return
    link = context.args[0]
    await update.message.reply_text(f"🔍 Информация о треке:\n{link}\n(будет извлекаться в будущем обновлении)")


async def download_track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 1:
        await update.message.reply_text("⚠️ Укажи ссылку на трек. Пример: /download https://open.qobuz.com/track/12345")
        return
    link = context.args[0]
    await update.message.reply_text(f"⬇️ Начинаю загрузку трека:\n{link}\n(реализация в следующем шаге)")


# --- Запуск --- #

async def post_init(app):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"🤖 KuzyMusicBot запущен в {now}")
    if ADMIN_USER_ID:
        try:
            await app.bot.send_message(chat_id=ADMIN_USER_ID, text=f"🤖 KuzyMusicBot запущен\n🕒 {now}")
        except Exception as e:
            logger.warning(f"❌ Не удалось отправить сообщение админу: {e}")


def main():
    logger.info("🚀 KuzyMusicBot запускается...")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Регистрируем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("qobuz", qobuz_info))
    app.add_handler(CommandHandler("track", track_info))
    app.add_handler(CommandHandler("download", download_track))

    # Обработка всех ошибок
    async def error_handler(update, context):
        logger.error(f"❗ Ошибка: {context.error}")
        if update and update.message:
            await update.message.reply_text("Произошла ошибка. Попробуй ещё раз позже.")

    app.add_error_handler(error_handler)

    app.run_polling()


if __name__ == "__main__":
    main()