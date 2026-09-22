"""
Единый источник правды о том, ссылки каких сервисов понимает бот.

Раньше список доменов был продублирован: отдельно в фильтре main.py и
отдельно в роутере handlers.py. Списки разошлись (main.py не пропускал
geo.music.apple.com и www.qobuz.com), и такие ссылки молча игнорировались —
сообщение просто не доходило до обработчика. Теперь список один.
"""
import re
from typing import Optional

# Порядок проверки важен: домены пересекаются редко, но порядок фиксируем.
# Поддомены разрешены любые: geo.music.apple.com, classical.music.apple.com,
# www.qobuz.com, play.qobuz.com и т.д.
SOURCE_PATTERNS = (
    ("apple", r"(?:[a-z0-9-]+\.)*(?:music|itunes)\.apple\.com/"),
    ("qobuz", r"(?:[a-z0-9-]+\.)*qobuz\.com/"),
    ("spotify", r"(?:[a-z0-9-]+\.)*spotify\.com/"),
)

# Схему делаем необязательной: люди часто вставляют ссылку без https://.
# Граница слева не даёт принять myqobuz.com за qobuz.com.
_URL_PREFIX = r"(?:https?://)?(?<![a-zA-Z0-9_.-])"

# Общий шаблон для фильтра сообщений в main.py
SUPPORTED_URL_PATTERN = _URL_PREFIX + "(?:" + "|".join(p for _, p in SOURCE_PATTERNS) + ")"

_COMPILED = {
    source: re.compile(_URL_PREFIX + pattern, re.IGNORECASE)
    for source, pattern in SOURCE_PATTERNS
}


def detect_source(url: str) -> Optional[str]:
    """Возвращает 'apple' | 'qobuz' | 'spotify' или None, если ссылка не наша."""
    if not url:
        return None
    for source, pattern in _COMPILED.items():
        if pattern.search(url):
            return source
    return None
