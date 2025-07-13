import os
import subprocess
import glob
import shutil
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# 🔧 Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Установи переменную окружения в systemd или .env
VENV_PYTHON = "/opt/qobuz-env/bin/python"
QOBUZ_DL = "/opt/qobuz-env/bin/qobuz-dl"
DOWNLOAD_DIR = os.path.expanduser("~/Qobuz Downloads")

# 🎯 Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# 👋 /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎧 KuzyMusicBot запущен!\nПросто отправь /download <ссылка на Qobuz трек>")


# ⬇️ /download
async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи ссылку на трек Qobuz после команды.")
        return

    url = context.args[0]
    await update.message.reply_text(f"⬇️ Начинаю загрузку трека:\n{url}")

    try:
        # 🧹 Очистка старой папки
        if os.path.exists(DOWNLOAD_DIR):
            shutil.rmtree(DOWNLOAD_DIR)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # 🚀 Запуск загрузки
        result = subprocess.run(
            [QOBUZ_DL, "dl", url],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info("Загрузка завершена:\n" + result.stdout)

        # 🔍 Поиск файлов
        flac_files = glob.glob(os.path.join(DOWNLOAD_DIR, "**/*.flac"), recursive=True)
        cover_files = glob.glob(os.path.join(DOWNLOAD_DIR, "**/cover.jpg"), recursive=True)

        if not flac_files:
            await update.message.reply_text("😢 Трек не найден после загрузки.")
            return

        # 🎵 Отправка аудио
        flac_path = flac_files[0]
        with open(flac_path, "rb") as audio_file:
            await update.message.reply_audio(audio=audio_file, title="🎶 Твоя загрузка с Qobuz")

        # 🖼 Отправка обложки
        if cover_files:
            with open(cover_files[0], "rb") as cover:
                await update.message.reply_photo(photo=cover, caption="📀 Обложка альбома")

        # 🧹 Удаление
        shutil.rmtree(DOWNLOAD_DIR)
        logger.info("Удалены временные файлы")

    except subprocess.CalledProcessError as e:
        logger.error("Ошибка загрузки:\n" + e.stderr)
        await update.message.reply_text("❌ Ошибка при загрузке трека.")
    except Exception as e:
        logger.error("Непредвиденная ошибка:\n" + str(e))
        await update.message.reply_text("⚠️ Что-то пошло не так.")


# 🚀 Запуск
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("download", handle_download))

    logger.info("KuzyMusicBot запущен")
    application.run_polling()


if __name__ == "__main__":
    main()