from pathlib import Path
from typing import Optional, Tuple
from config import Config
import logging
import os
import subprocess
import re
import sys
import shutil
import requests # <-- Добавляем импорт requests
from qobuz_dl.core import QobuzDL # <-- Убедитесь, что этот импорт есть

logger = logging.getLogger(__name__)

class QobuzDownloader:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Инициализируем клиент, чтобы получить доступ к его app_id
            self.client = QobuzDL()
            logger.info("✅ Клиент Qobuz успешно инициализирован.")
        except Exception as e:
            logger.exception("❌ Не удалось инициализировать клиент Qobuz! Убедитесь, что вы выполнили 'qobuz-dl -r' на сервере.")
            self.client = None

    # --- НОВЫЙ, НАДЕЖНЫЙ МЕТОД ПОИСКА ЧЕРЕЗ API ---
    def search_track(self, artist: str, title: str) -> Optional[str]:
        if not self.client:
            logger.error("❌ Клиент Qobuz не инициализирован, поиск невозможен.")
            return None
        
        query = f"{artist} {title}"
        logger.info(f"🔍 Поиск на Qobuz через API по запросу: '{query}'")
        
        search_url = "https://www.qobuz.com/api.json/0.2/track/search"
        
        # Используем app_id из инициализированного клиента
        app_id = getattr(self.client, 'app_id', None)
        if not app_id:
            logger.error("❌ Не удалось получить app_id из клиента Qobuz.")
            return None

        params = { "query": query, "limit": 5, "app_id": app_id }

        try:
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            results = response.json()

            if results and results.get('tracks', {}).get('items'):
                # Ищем наиболее релевантный результат
                for item in results['tracks']['items']:
                    track_title = item.get('title', '').lower()
                    performer = item.get('performer', {}).get('name', '').lower()
                    if title.lower() in track_title and artist.lower() in performer:
                        track_id = item['id']
                        url = f"https://open.qobuz.com/track/{track_id}"
                        logger.info(f"✅ Найден точный трек на Qobuz: {url}")
                        return url
                
                # Если точного совпадения нет, берем первый результат
                first_track = results['tracks']['items'][0]
                track_id = first_track['id']
                url = f"https://open.qobuz.com/track/{track_id}"
                logger.info(f"⚠️ Точное совпадение не найдено, взят первый результат: {url}")
                return url

        except requests.RequestException as e:
            logger.error(f"❌ Сетевая ошибка при поиске через API Qobuz: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке результатов поиска API Qobuz: {e}")
        
        logger.warning(f"❌ Трек '{query}' не найден на Qobuz через API.")
        return None

    async def download_track(self, url: str, quality_id: int) -> Tuple[Optional[Path], Optional[Path]]:
        # ... (этот метод остается без изменений, он использует CLI)
        logger.info(f"⬇️ Запуск скачивания через CLI для URL: {url} с качеством ID: {quality_id}")
        try:
            venv_path = Path(sys.executable).parent.parent
            qobuz_dl_path = venv_path / "bin" / "qobuz-dl"

            for item in self.download_dir.glob("**/*"):
                if item.is_file(): item.unlink()
                elif item.is_dir(): shutil.rmtree(item)

            command = [
                str(qobuz_dl_path), "dl", url,
                "-q", str(quality_id),
                "--embed-art", "-d", str(self.download_dir)
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)

            if "Invalid credentials" in result.stderr:
                logger.error("❌ Ошибка аутентификации Qobuz. Пожалуйста, выполните 'qobuz-dl -r' на сервере.")
                return None, None
            if result.returncode != 0:
                logger.error(f"❌ Команда 'qobuz-dl dl' завершилась с ошибкой: {result.stderr}")
                return None, None
            
            logger.info("✅ Скачивание через CLI завершено. Поиск файлов...")
            return self._find_downloaded_files()
            
        except Exception as e:
            logger.error(f"❌ Ошибка при скачивании через CLI: {e}")
            return None, None

    def _find_downloaded_files(self) -> Tuple[Optional[Path], Optional[Path]]:
        for f in self.download_dir.glob("**/*.*"):
            if f.is_file() and f.suffix in {".flac", ".mp3", ".m4a", ".wav"}:
                return f, f.parent / "cover.jpg"
        return None, None