# main.py

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest # <-- Важный импорт для локального API

from bot.handlers import start, help_command, handle_download, handle_audio_recognition
from config import Config
from dotenv import load_dotenv

# --- ВОССТАНОВИТЬ ЭТУ ФУНКЦИЮ! ---
def setup_logging():
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
# -----------------------------------

def main():
    load_dotenv()
    # Ошибка здесь: функция должна быть определена выше!
    setup_logging() 
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Запуск бота...")
    
    # Конфигурация локального API (как мы ее обновили)
    LOCAL_API_ROOT = "http://127.0.0.1:8081/bot"
    
    local_request = HTTPXRequest(
        base_url=LOCAL_API_ROOT,
        connect_timeout=30,
        read_timeout=120,
        write_timeout=120,
    )

    app = (
        ApplicationBuilder()
        .token(Config.BOT_TOKEN)
        .request(local_request)
        .build()
    )
    # ... (обработчики) ...

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