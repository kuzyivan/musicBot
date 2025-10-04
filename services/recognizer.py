import logging
from audd.client import AudD
from config import Config
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class AudioRecognizer:
    def __init__(self):
        self.client = AudD(api_token=Config.AUDD_API_TOKEN)
        logger.info("Клиент AudD.io инициализирован.")

    def recognize(self, file_path: str) -> Optional[Dict[str, str]]:
        """
        Распознает аудиофайл с помощью AudD.io и возвращает 
        {'artist': ..., 'title': ...} или None.
        """
        logger.info(f"Отправка файла {file_path} на распознавание в AudD.io...")
        try:
            result = self.client.recognize(file_path)
            
            if result and result.get('status') == 'success' and result.get('result'):
                track_info = result['result']
                artist = track_info.get('artist')
                title = track_info.get('title')

                if artist and title:
                    logger.info(f"AudD.io распознал трек: {artist} - {title}")
                    return {'artist': artist, 'title': title}

            logger.warning(f"AudD.io не смог распознать трек. Ответ: {result}")
            return None

        except Exception as e:
            logger.error(f"Произошла ошибка при обращении к AudD.io: {e}")
            return None