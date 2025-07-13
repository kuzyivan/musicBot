from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import subprocess
import os
import glob

# Путь до твоего виртуального окружения
VENV_PYTHON = "/opt/qobuz-env/bin/python"
QOBUZ_DL = "/opt/qobuz-env/bin/qobuz-dl"
DOWNLOAD_DIR = os.path.expanduser("~/Qobuz Downloads")

async def download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🎵 Пришли ссылку на трек, например:\n/download https://open.qobuz.com/track/118882834")
        return

    url = context.args[0]
    await update.message.reply_text("⏬ Начинаю загрузку трека... Приготовь уши 👂🔥")

    try:
        # Запуск загрузки трека
        subprocess.run([QOBUZ_DL, "dl", url], check=True)

        # Поиск загруженного файла
        audio_files = glob.glob(os.path.join(DOWNLOAD_DIR, "**", "*.flac"), recursive=True)
        cover_files = glob.glob(os.path.join(DOWNLOAD_DIR, "**", "cover.jpg"), recursive=True)

        if not audio_files:
            await update.message.reply_text("⚠️ Не удалось найти аудиофайл после загрузки.")
            return

        # Отправка аудиофайла
        audio_path = audio_files[0]
        await context.bot.send_audio(chat_id=update.effective_chat.id, audio=open(audio_path, 'rb'))

        # Отправка обложки (если найдена)
        if cover_files:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=open(cover_files[0], 'rb'))

        # Удаление всех файлов
        for file_path in audio_files + cover_files:
            os.remove(file_path)

    except subprocess.CalledProcessError as e:
        await update.message.reply_text("❌ Ошибка при загрузке трека.")
        print(f"[ERROR] Qobuz download error: {e}")

# Регистрируем команду
app = ApplicationBuilder().token("ТВОЙ_ТОКЕН").build()
app.add_handler(CommandHandler("download", download_handler))

if __name__ == "__main__":
    app.run_polling()