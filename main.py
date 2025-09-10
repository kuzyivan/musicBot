import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from bot.handlers import start, help_command, handle_download
from config import Config
from dotenv import load_dotenv

def setup_logging():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.DEBUG,
        filename=Config.LOG_FILE,
        filemode="a"
    )

def main():
    load_dotenv()
    setup_logging()
    app = ApplicationBuilder().token(Config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))

    app.run_polling()

if __name__ == "__main__":
    main()