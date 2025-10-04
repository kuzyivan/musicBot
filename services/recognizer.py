import requests
import logging
from config import Config
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class AudioRecognizer:
    def __init__(self):
        # Берем токен из нашей стандартной конфигурации
        self.api_token = Config.AUDD_API_TOKEN
        self.api_url = "https://api.audd.io/"
        logger.info("Сервис распознавания (на базе requests) инициализирован.")

    def recognize(self, file_path: str) -> Optional[Dict[str, str]]:
        """
        Распознает аудиофайл, отправляя его напрямую в AudD.io,
        и возвращает {'artist': ..., 'title': ...} или None.
        """
        logger.info(f"Отправка файла {file_path} на распознавание в AudD.io...")
        try:
            with open(file_path, 'rb') as f:
                # Готовим данные для POST-запроса
                files = {'file': f}
                data = {'api_token': self.api_token}
                
                # Отправляем запрос
                response = requests.post(self.api_url, files=files, data=data)
                response.raise_for_status()  # Проверяем на HTTP ошибки (4xx, 5xx)
                result_json = response.json()

            # Обрабатываем ответ, как и раньше
            if result_json.get('status') == 'success' and result_json.get('result'):
                track_info = result_json['result']
                artist = track_info.get('artist')
                title = track_info.get('title')
                if artist and title:
                    logger.info(f"Распознано: {artist} - {title}")
                    return {'artist': artist, 'title': title}

            logger.warning(f"AudD.io не смог распознать трек. Ответ: {result_json}")
            return None

        except requests.RequestException as e:
            logger.error(f"Ошибка сети при обращении к AudD.io: {e}")
            return None
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при распознавании: {e}")
            return None