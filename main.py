import logging
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from bot.handlers import start, help_command, handle_download
from config import Config
from dotenv import load_dotenv

def setup_logging():
    # Убедитесь, что директория для логов существует
    Config.LOG_FILE.parent.mkdir(exist_ok=True)
    
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO, # Рекомендуется INFO для продакшена, DEBUG для отладки
        handlers=[
            logging.FileHandler(Config.LOG_FILE, mode="a"),
            logging.StreamHandler() # Добавляем вывод в консоль
        ]
    )

def main():
    load_dotenv()
    setup_logging()
    app = ApplicationBuilder().token(Config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("download", handle_download))
    
    # --- ДОБАВЛЕН НОВЫЙ ОБРАБОТЧИК ---
    # Он будет ловить все текстовые сообщения, которые содержат "qobuz.com/track/"
    # и не являются командами
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"qobuz\.com/track/"), 
        handle_download
    ))

    app.run_polling()

if __name__ == "__main__":
    main()