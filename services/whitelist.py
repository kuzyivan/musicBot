import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_WHITELIST_FILE = Path(__file__).resolve().parent.parent / "whitelist.json"
_whitelist: set[int] = set()


def load() -> None:
    global _whitelist
    try:
        if _WHITELIST_FILE.exists():
            _whitelist = set(json.loads(_WHITELIST_FILE.read_text()))
            logger.info(f"✅ Whitelist загружен: {_whitelist}")
        else:
            _whitelist = set()
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки whitelist: {e}")
        _whitelist = set()


def _save() -> None:
    _WHITELIST_FILE.write_text(json.dumps(list(_whitelist)))


def is_allowed(user_id: int, admin_id: int) -> bool:
    return user_id == admin_id or user_id in _whitelist


def add(user_id: int) -> bool:
    if user_id in _whitelist:
        return False
    _whitelist.add(user_id)
    _save()
    return True


def remove(user_id: int) -> bool:
    if user_id not in _whitelist:
        return False
    _whitelist.discard(user_id)
    _save()
    return True


def all_users() -> set[int]:
    return set(_whitelist)
