# main.py

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
# HTTPXRequest больше не нужен, если мы используем base_url
# from telegram.request import HTTPXRequest 

from bot.handlers import start, help_command, handle_download, handle_audio_recognition
from config import Config
from dotenv import load_dotenv

def setup_logging():
    # ... (Оставьте функцию setup_logging без изменений)
    Config.LOG_FILE.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[
            logging.FileHandler(Config.LOG_FILE, mode="a"),
            logging.StreamHandler()
        ]
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext").setLevel(logging.WARNING)

def main():
    load_dotenv()
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Запуск бота...")
    
    # --- НАЧАЛО ОКОНЧАТЕЛЬНОГО ИСПРАВЛЕНИЯ ---
    
    # Определяем полный URL, включая /bot
    LOCAL_API_ROOT = "http://127.0.0.1:8081/bot"
    
    # ApplicationBuilder позволяет установить базовый URL через .base_url()
    app = (
        ApplicationBuilder()
        .token(Config.BOT_TOKEN)
        # КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: используем base_url для указания локального API
        .base_url(LOCAL_API_ROOT) 
        .connect_timeout(30)
        .read_timeout(120)
        .write_timeout(120)
        .build()
    )
    # --- КОНЕЦ ОКОНЧАТЕЛЬНОГО ИСПРАВЛЕНИЯ ---

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("download", handle_download))
    
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"https?:\/\/(open|play)\.(qobuz|spotify)\.com\/"), 
        handle_download
    ))
    
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, handle_audio_recognition))

    app.run_polling()

if __name__ == "__main__":
    main()