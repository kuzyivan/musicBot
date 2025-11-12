# main.py

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
# --- НОВЫЙ ИМПОРТ ---
from telegram.request import HTTPXRequest 
# --------------------

from bot.handlers import start, help_command, handle_download, handle_audio_recognition
from config import Config
from dotenv import load_dotenv

# ... (функция setup_logging остается без изменений) ...

def main():
    load_dotenv()
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Запуск бота...")
    
    # --- НАЧАЛО ИЗМЕНЕНИЯ: КОНФИГУРАЦИЯ ЛОКАЛЬНОГО API ---
    # Указываем адрес нашего локального Bot API Server
    LOCAL_API_ROOT = "http://127.0.0.1:8081/bot"
    
    # Создаем объект запроса, который будет использовать наш локальный URL
    local_request = HTTPXRequest(
        base_url=LOCAL_API_ROOT,
        # Увеличиваем таймауты для больших файлов (опционально, но рекомендуется)
        connect_timeout=30,
        read_timeout=120,
        write_timeout=120,
    )

    app = (
        ApplicationBuilder()
        .token(Config.BOT_TOKEN)
        .request(local_request) # <-- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: используем локальный запрос
        .build()
    )
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    # Обработчики остаются без изменений
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))
    app.add_handler(MessageHandler(filters.AUDIO, handle_audio_recognition))

    app.run_polling()

if __name__ == "__main__":
    main()