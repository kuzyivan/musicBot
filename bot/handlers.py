from telegram import Update
from telegram.ext import ContextTypes
from services.downloader import QobuzDownloader
from services.savify_downloader import SavifyDownloader 
from services.file_manager import FileManager
from services.recognizer import AudioRecognizer
from config import Config
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import shutil
import mutagen 
import asyncio # Импорт нужен для asyncio.get_running_loop() и run_in_executor
from io import BytesIO # <-- ДОБАВЛЕНО для работы с байтами

logger = logging.getLogger(__name__)

# --- Вспомогательные функции (без изменений) ---

def embed_cover_art(audio_path: Path, cover_path: Optional[Path]):
    if not all([audio_path, cover_path, audio_path.exists(), cover_path.exists()]):
        return
    logger.info(f"🖼️ Встраивание обложки {cover_path.name} в файл {audio_path.name}...")
    temp_output_path = audio_path.with_suffix(f".temp{audio_path.suffix}")
    try:
        command = [
            "ffmpeg", "-i", str(audio_path), "-i", str(cover_path), "-map", "0:a",
            "-map", "1:v", "-c", "copy", "-disposition:v:0", "attached_pic",
            "-id3v2_version", "3", str(temp_output_path)
        ]
        subprocess.run(command, check=True, capture_output=True)
        shutil.move(str(temp_output_path), str(audio_path))
        logger.info("✅ Обложка успешно встроена.")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Не удалось встроить обложку с помощью ffmpeg: {e.stderr.decode()}")
    except Exception as e:
        logger.error(f"❌ Не удалось встроить обложку: {e}")
    finally:
        if temp_output_path.exists(): temp_output_path.unlink()

def convert_to_mp3(file_path: Path) -> Optional[Path]:
    mp3_path = file_path.with_suffix(".mp3")
    logger.info(f"🎵 Конвертация файла {file_path.name} в MP3...")
    try:
        command = [
            "ffmpeg", "-i", str(file_path), "-map", "0:a:0", "-b:a", "320k",
            "-map", "0:v?", "-c:v", "copy", "-id3v2_version", "3", str(mp3_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        logger.info(f"✅ Файл успешно сконвертирован в {mp3_path.name}")
        return mp3_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Ошибка конвертации ffmpeg: {e.stderr.decode()}")
        return None

QUALITY_HIERARCHY = {
    "HI-RES (Max)": 27,
    "HI-RES (<96kHz)": 7,
    "CD (16-bit)": 6,
    "MP3 (320 kbps)": 5,
}

# --- Команды Start/Help (без изменений) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎵 Привет! Я бот версии 2.0 и могу скачивать треки с Qobuz и Spotify. 🚀")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — приветствие\n"
        "/download <ссылка> — скачать трек (Qobuz или Spotify)\n"
        "Или просто отправь аудио для распознавания."
    )

# --- НОВЫЙ УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК ЗАГРУЗКИ (без изменений) ---

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный обработчик-маршрутизатор. 
    Определяет тип ссылки и вызывает нужный воркер.
    """
    url = context.args[0] if context.args else getattr(getattr(update, 'message', None), 'text', '').strip()
    if not url: return

    if re.search(r"qobuz\.com/", url):
        await _download_qobuz(update, context, url)
    elif re.search(r"spotify\.com/", url):
        await _download_spotify(update, context, url)
    else:
        await update.message.reply_text("❌ Пожалуйста, отправьте корректную ссылку на Qobuz или Spotify.")


async def _download_qobuz(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """
    Логика скачивания с Qobuz.
    """
    downloader = QobuzDownloader()
    file_manager = FileManager()
    sent_message = await update.message.reply_text("⏳ Начинаю поиск на Qobuz...")
    
    try:
        for quality_name, quality_id in QUALITY_HIERARCHY.items():
            base_text = f"💿 Qobuz: Качество {quality_name}\n"
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, 
                message_id=sent_message.message_id, 
                text=f"{base_text}⏳ Подготовка к скачиванию..."
            )
            
            async def progress_callback(percent):
                progress_bar = file_manager.format_progress_bar(percent)
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=sent_message.message_id,
                        text=f"{base_text}{progress_bar}"
                    )
                except Exception:
                    # Игнорируем ошибки обновления (например, если сообщение не изменилось)
                    pass

            audio_file, cover_file = await downloader.download_track(
                url, quality_id, progress_callback=progress_callback
            )
            
            if audio_file:
                await process_and_send_audio(
                    update, context, sent_message, 
                    audio_file, cover_file, 
                    url_for_caption=url, source="Qobuz"
                )
                return 
            
            logger.warning(f"⚠️ Qobuz: Файл для качества '{quality_name}' не был скачан. Пробую следующее.")

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, 
            message_id=sent_message.message_id, 
            text="❌ Qobuz: Не удалось скачать файл ни в одном из доступных качеств."
        )
    
    except Exception as e:
        logger.exception(f"❌ Qobuz: Общая ошибка при обработке запроса: {e}")
        await update.message.reply_text(f"❌ Qobuz: Произошла ошибка: {e}")


async def _download_spotify(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """
    Новая логика для скачивания из Spotify с помощью Savify.
    """
    downloader = SavifyDownloader()
    sent_message = await update.message.reply_text("⏳ Начинаю поиск на Spotify...")

    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, 
            message_id=sent_message.message_id, 
            text=f"💿 Spotify: Ищу трек и скачиваю (через YouTube)..."
        )
        
        audio_file, cover_file = await downloader.download_track(url)
        
        if audio_file:
            await process_and_send_audio(
                update, context, sent_message, 
                audio_file, cover_file, 
                url_for_caption=url, source="Spotify"
            )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, 
                message_id=sent_message.message_id, 
                text="❌ Spotify: Не удалось скачать файл. Возможно, он не найден на YouTube."
            )
    except Exception as e:
        logger.exception(f"❌ Spotify: Общая ошибка при обработке запроса: {e}")
        await update.message.reply_text(f"❌ Spotify: Произошла ошибка: {e}")


# --- УЛУЧШЕННЫЙ ОБРАБОТЧИК ОТПРАВКИ (ИЗМЕНЕНИЕ ЛИМИТА) ---

async def process_and_send_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sent_message,
    initial_audio_file: Path,
    initial_cover_file: Optional[Path],
    url_for_caption: str,
    source: str 
):
    """
    УНИВЕРСАЛЬНАЯ функция.
    Обрабатывает, конвертирует и отправляет ЛЮБОЙ скачанный файл.
    """
    file_manager = FileManager()
    files_to_delete = set()
    track_details = {}

    try:
        if not initial_audio_file or not initial_audio_file.exists():
            await sent_message.edit_text("❌ Не удалось найти скачанный аудиофайл.")
            return

        files_to_delete.add(initial_audio_file)
        if initial_cover_file:
            files_to_delete.add(initial_cover_file)

        embed_cover_art(initial_audio_file, initial_cover_file)
        
        await sent_message.edit_text("💿 Файл скачан, проверяю размер...")
        size_mb = file_manager.get_file_size_mb(initial_audio_file)
        logger.info(f"ℹ️ Проверка файла: Размер = {size_mb:.2f} MB")
        
        audio_file_to_send = initial_audio_file
        
        # --- ИЗМЕНЕНИЕ: Используем Config.MAX_FILE_SIZE_MB (2000 МБ) вместо 48 МБ ---
        if size_mb > Config.MAX_FILE_SIZE_MB: 
            await sent_message.edit_text(f"🎧 Файл слишком большой ({size_mb:.2f} MB). Конвертирую в MP3...")
            converted_file = convert_to_mp3(initial_audio_file)
            if converted_file:
                files_to_delete.add(converted_file)
                audio_file_to_send = converted_file
            else:
                logger.error("❌ Конвертация в MP3 не удалась. Отправка невозможна.")
                await sent_message.edit_text("❌ Файл слишком большой, и не удалось его сконвертировать.")
                return

        await sent_message.edit_text("📤 Файл готов, начинается отправка...")

        track_details = _get_metadata_from_file(audio_file_to_send)
        
        if not track_details.get('title') or track_details.get('title') == 'N/A':
            logger.warning("Не удалось прочитать ID3-теги, парсим имя папки...")
            track_details = _get_metadata_from_qobuz_path(audio_file_to_send)
        
        real_quality = file_manager.get_audio_quality(audio_file_to_send) or "N/A"
        if "MP3" in real_quality and source == "Spotify":
             real_quality = "MP3 (до 320 kbps)"

        ext = audio_file_to_send.suffix
        custom_filename = (
            f"{track_details.get('artist', 'Unknown')} - "
            f"{track_details.get('title', 'Unknown')} "
            f"({track_details.get('album', 'Unknown')}, {track_details.get('year', 'N/A')}){ext}"
        )

        caption_text = (
            f"🎤 **Артист:** `{track_details.get('artist', 'N/A')}`\n"
            f"🎵 **Трек:** `{track_details.get('title', 'N/A')}`\n"
            f"💿 **Альбом:** {track_details.get('album', 'N/A')}\n"
            f"🗓️ **Год:** {track_details.get('year', 'N/A')}\n\n"
            f"✨ **Качество:** {real_quality}\n\n"
            f"Скачано с [{source}]({url_for_caption})"
        )

        # 1. Отправляем аудиофайл БЕЗ подписи
        with open(audio_file_to_send, 'rb') as f:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id, 
                audio=f, 
                filename=custom_filename
            )
        
        # 2. Отправляем обложку С ПОДПИСЬЮ
        if initial_cover_file and initial_cover_file.exists():
            with open(initial_cover_file, 'rb') as img:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id, 
                    photo=img, 
                    caption=caption_text, 
                    parse_mode='Markdown'
                )
        else:
            # 3. Если обложки нет, просто отправляем подпись текстом
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=caption_text,
                parse_mode='Markdown'
            )
        
        await sent_message.delete()

    finally:
        logger.info("🗑️ Очистка временных файлов после отправки...")
        for file_to_delete in files_to_delete:
            file_manager.safe_remove(file_to_delete)
        logger.info("✅ Временные файлы удалены.")


def _get_metadata_from_file(file_path: Path) -> dict:
    """Читает ID3-теги (для MP3 от Savify) или FLAC-теги."""
    details = {}
    try:
        audio = mutagen.File(file_path)
        if not audio:
            return {}
        
        details['artist'] = audio.get('artist', ['N/A'])[0]
        details['title'] = audio.get('title', ['N/A'])[0]
        details['album'] = audio.get('album', ['N/A'])[0]
        
        year = (audio.get('date', []) or 
                audio.get('TDRC', []) or 
                audio.get('TDRL', []) or 
                ['N/A'])
        
        details['year'] = re.sub(r'[^0-9]', '', str(year[0]))[:4]
        if not details['year']: details['year'] = 'N/A'

        return details
    except Exception as e:
        logger.warning(f"Не удалось прочитать метаданные mutagen: {e}")
        return {}


def _get_metadata_from_qobuz_path(audio_file: Path) -> dict:
    """Ваша старая логика парсинга пути Qobuz (как запасной вариант)."""
    try:
        original_name = Path(str(audio_file).replace(".mp3", ".flac")).name
        album_folder = audio_file.parent.name
        match = re.match(r"(?P<artist>.+?) - (?P<album>.+?) \((?P<year>\d{4})", album_folder)
        
        details = {}
        details.update(zip(['artist', 'album', 'year'], map(str.strip, match.groups())) if match else zip(['artist', 'album', 'year'], ["Unknown"]*3))
        details['title'] = re.sub(r"^\d+\.\s*", "", original_name.rsplit(".", 1)[0]).strip()
        return details
    except Exception:
        return {}


# --- РАСПОЗНАВАНИЕ АУДИО (ИСПРАВЛЕНО) ---

async def handle_audio_recognition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    audio_source = message.audio or message.voice
    if not audio_source: return

    sent_message = await message.reply_text("🔎 Получил аудио, пытаюсь распознать...")
    temp_file_path = None
    converted_file_path = None 
    
    try:
        file_obj = await audio_source.get_file()
        
        # --- НАЧАЛО ИСПРАВЛЕНИЯ: Асинхронное скачивание в байты и сохранение на диск ---
        await sent_message.edit_text("⏳ Скачиваю аудио...")
        # Скачиваем файл асинхронно в память
        file_bytes = await file_obj.download_as_bytearray() 
        
        temp_file_path = Path(f"{file_obj.file_id}{Path(file_obj.file_path).suffix or '.ogg'}")
        
        # Сохраняем байты на диск (синхронная операция в executor)
        loop = context.application.loop 
        await loop.run_in_executor(None, temp_file_path.write_bytes, bytes(file_bytes))
        # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
        
        # --- БЛОК КОНВЕРТАЦИИ В MP3 (включая удаление, как в предыдущем исправлении) ---
        converted_file_path = temp_file_path.with_suffix(".mp3")
        await sent_message.edit_text("⏳ Конвертирую аудио для распознавания...")
        
        command = [
            "ffmpeg", "-i", str(temp_file_path), "-vn", "-acodec", "libmp3lame", 
            "-b:a", "192k", str(converted_file_path)
        ]
        
        # Запуск блокирующей операции в executor
        await loop.run_in_executor(None, subprocess.run, command, {"check": True, "capture_output": True})
        
        file_to_recognize = converted_file_path
        # ----------------------------------------
        
        recognizer = AudioRecognizer()
        # Отправляем на распознавание сконвертированный файл
        track_info = recognizer.recognize(str(file_to_recognize))
        
        if not track_info:
            await sent_message.edit_text("❌ К сожалению, не удалось распознать этот трек.")
            return

        artist, title = track_info['artist'], track_info['title']
        await sent_message.edit_text(f"✅ Распознано: `{artist} - {title}`. Ищу и скачиваю с Qobuz...", parse_mode='Markdown')
        
        downloader = QobuzDownloader()
        audio_file, cover_file = downloader.search_and_download_lucky(artist, title)
        
        if not audio_file:
            await sent_message.edit_text(f"❌ Трек `{artist} - {title}` не найден на Qobuz.", parse_mode='Markdown')
            return

        fake_url = "https://qobuz.com"
        await process_and_send_audio(
            update, context, sent_message, 
            audio_file, cover_file, 
            fake_url, source="Qobuz (via Shazam)"
        )

    except Exception as e:
        logger.error(f"❌ Ошибка в процессе распознавания: {e}")
        await sent_message.edit_text("❌ Произошла непредвиденная ошибка во время распознавания.")
    finally:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()
        # --- ДОБАВЛЕНО УДАЛЕНИЕ СКОНВЕРТИРОВАННОГО ФАЙЛА ---
        if converted_file_path and converted_file_path.exists():
            converted_file_path.unlink()
        # --- КОНЕЦ ДОБАВЛЕНИЯ ---