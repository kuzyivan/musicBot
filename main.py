# main.py

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
# Мы продолжим использовать HTTPXRequest, но не будем передавать base_url напрямую.
from telegram.request import HTTPXRequest 

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
    
    # --- НАЧАЛО ИСПРАВЛЕНИЯ ОШИБКИ: ИСПОЛЬЗУЕМ API_URL В BUILDER'Е ---
    
    # 1. Определяем базовый URL локального сервера (он включает /bot)
    LOCAL_API_URL = "http://127.0.0.1:8081"
    
    # 2. Создаем request-объект, передавая только таймауты (без base_url)
    local_request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=120,
        write_timeout=120,
    )

    # 3. Передаем request-объект И API_URL в ApplicationBuilder
    # NOTE: API_URL должен быть базовым URL, НЕ включая /bot<TOKEN>/
    app = (
        ApplicationBuilder()
        .token(Config.BOT_TOKEN)
        .request(local_request) 
        .api_url(LOCAL_API_URL) # <-- КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Указываем URL здесь!
        .build()
    )
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

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