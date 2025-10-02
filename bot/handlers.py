from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.file_manager import FileManager
from config import Config
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional
from mutagen.flac import FLAC, Picture # Импортируем mutagen для FLAC

logger = logging.getLogger(__name__)

# --- Новая функция для встраивания обложки ---
def embed_cover_art(audio_path: Path, cover_path: Path):
    if not audio_path or not cover_path or not audio_path.exists() or not cover_path.exists():
        return
    
    logger.info(f"Встраивание обложки {cover_path} в файл {audio_path}...")
    try:
        if audio_path.suffix == '.flac':
            audio = FLAC(audio_path)
            audio.clear_pictures()
            pic = Picture()
            with open(cover_path, 'rb') as f:
                pic.data = f.read()
            pic.type = 3  # Front cover
            pic.mime = 'image/jpeg'
            audio.add_picture(pic)
            audio.save()
            logger.info("Обложка успешно встроена во FLAC.")
        # Для MP3 встраивание происходит на этапе конвертации
    except Exception as e:
        logger.error(f"Не удалось встроить обложку с помощью mutagen: {e}")

# --- Обновленная функция конвертации, которая также копирует обложку ---
def convert_to_mp3(file_path: Path) -> Optional[Path]:
    mp3_path = file_path.with_suffix(".mp3")
    logger.info(f"Конвертация файла {file_path} в MP3 с сохранением обложки...")
    try:
        command = [
            "ffmpeg", "-i", str(file_path), "-map", "0:a:0", "-b:a", "320k",
            "-map", "0:v?", "-c:v", "copy", "-id3v2_version", "3", str(mp3_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        logger.info(f"Файл успешно сконвертирован в {mp3_path}")
        return mp3_path
    except Exception as e:
        logger.error(f"Ошибка конвертации ffmpeg: {e}")
        return None

# --- Словарь качеств ---
QUALITY_HIERARCHY = { "HI-RES (Max)": 27, "CD (16-bit)": 6, "MP3 (320 kbps)": 5 }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Я могу скачивать треки с Qobuz.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — приветствие\n/download <ссылка> — скачать трек")

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = context.args[0] if context.args else getattr(getattr(update, 'message', None), 'text', '').strip()
    # ... (проверки url остаются такими же)

    chat_id = update.effective_chat.id
    # ... (проверки url остаются такими же)

    downloader = QobuzDownloader()
    file_manager = FileManager()
    
    audio_file_to_send, cover_file_to_send = None, None
    files_to_delete = set()
    track_details = {}

    try:
        sent_message = await update.message.reply_text("⏳ Начинаю поиск...")
        
        for i, (quality_name, quality_id) in enumerate(QUALITY_HIERARCHY.items()):
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"💿 Пробую скачать в качестве: {quality_name}...")
            
            audio_file, cover_file = await downloader.download_track(url, quality_id)
            if cover_file: files_to_delete.add(cover_file)
            if not audio_file: continue

            files_to_delete.add(audio_file)

            # --- ИЗМЕНЕНИЕ: Встраиваем обложку сразу после скачивания ---
            if audio_file and cover_file:
                embed_cover_art(audio_file, cover_file)

            size_mb = file_manager.get_file_size_mb(audio_file)
            
            if size_mb <= 48:
                audio_file_to_send, cover_file_to_send, track_details['quality_name'] = audio_file, cover_file, quality_name
                break
            else:
                is_last_attempt = (i == len(QUALITY_HIERARCHY) - 1)
                if is_last_attempt:
                    await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text=f"🎧 Файл слишком большой ({size_mb:.2f} MB). Конвертирую в MP3...")
                    converted_file = convert_to_mp3(audio_file)
                    if converted_file:
                        files_to_delete.add(converted_file)
                        audio_file_to_send, cover_file_to_send, track_details['quality_name'] = converted_file, cover_file, "MP3 (320 kbps)"
                    break

        if not audio_file_to_send:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="❌ Не удалось скачать файл. Возможно, трек слишком длинный.")
            return

        # ... (весь остальной код, включая формирование подписи и отправку, остается БЕЗ ИЗМЕНЕНИЙ)
        await context.bot.edit_message_text(chat_id=chat_id, message_id=sent_message.message_id, text="📤 Файл готов, начинается отправка...")

        original_name = Path(str(audio_file_to_send).replace(".mp3", ".flac")).name
        album_folder = audio_file_to_send.parent.name
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        track_details.update(zip(['artist', 'album', 'year'], map(str.strip, match.groups())) if match else zip(['artist', 'album', 'year'], ["Unknown"]*3))
        track_details['title'] = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0]).strip()
        
        ext = audio_file_to_send.suffix
        custom_filename = f"{track_details['artist']} - {track_details['title']} ({track_details['album']}, {track_details['year']}){ext}"
        
        quality_tech_info_match = re.search(r"\[(.*?)\]", album_folder)
        if quality_tech_info_match:
            real_quality = quality_tech_info_match.group(1).replace('B', '-bit').replace('k', ' k')
        elif track_details.get('quality_name') == "MP3 (320 kbps)":
            real_quality = "MP3 (320 kbps)"
        else:
            real_quality = "CD (16-bit / 44.1 kHz)"

        caption_text = (
            f"🎤 **Артист:** `{track_details.get('artist', 'N/A')}`\n"
            f"🎵 **Трек:** `{track_details.get('title', 'N/A')}`\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"🗓️ **Год:** {track_details.get('year', 'N/A')}\n\n"
            f"✨ **Качество:** {real_quality}\n\n"
            f"Скачано с [Qobuz]({url})"
        )
        
        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(chat_id=chat_id, audio=f, filename=custom_filename)

        if cover_file_to_send:
            with open(cover_file_to_send, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=chat_id, 
                    photo=img, 
                    caption=caption_text, 
                    parse_mode='Markdown'
                )
        
        await context.bot.delete_message(chat_id, sent_message.message_id)

    except Exception as e:
        logger.exception("Общая ошибка при обработке запроса")
        await update.message.reply_text(f"❌ Произошла ошибка: {e}")
    finally:
        logger.info("Очистка временных файлов...")
        for file_to_delete in files_to_delete:
            file_manager.safe_remove(file_to_delete)
        logger.info("Временные файлы удалены.")