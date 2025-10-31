import logging
# Убираем ненужный импорт (вы уже сделали)
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from bot.handlers import start, help_command, handle_download, handle_audio_recognition
from config import Config
from dotenv import load_dotenv

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

def main():
    load_dotenv()
    setup_logging()
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Запуск бота...")
    
    # --- ВАШИ УЛУЧШЕНИЯ С ТАЙМ-АУТАМИ (ОСТАВЛЕНЫ) ---
    app = (
        ApplicationBuilder()
        .token(Config.BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(120)
        .write_timeout(120)
        .build()
    )
    # --- КОНЕЦ БЛОКА С ТАЙМ-АУТАМИ ---

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("download", handle_download))
    
    # --- ОБНОВЛЕНИЕ ДЛЯ НОВОЙ ЛОГИКИ ЗДЕСЬ ---
    app.add_handler(MessageHandler(
        # Этот Regex теперь ловит только настоящие домены qobuz.com или spotify.com
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"https?:\/\/([a-zA-Z0-9\-]+\.)*(qobuz\.com|spotify\.com)\/"), 
        handle_download
    ))
    # --- КОНЕЦ ОБНОВЛЕНИЯ ---
    
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, handle_audio_recognition))

    app.run_polling()

if __name__ == "__main__":
    main()