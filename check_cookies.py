#!/usr/bin/env python3
"""
Проверка cookies.txt для Apple Music.

Проверяет ровно то, что требует gamdl:
  1. файл читается как Netscape-формат (разделители — ТАБЫ, не пробелы);
  2. в нём есть cookie media-user-token с доменом строго '.music.apple.com'.

Частая причина отказа: при копировании через терминал табы заменяются
пробелами, и MozillaCookieJar падает с 'invalid Netscape format'.
Флаг --fix чинит разделители автоматически (с бэкапом).

Запуск:  python3 check_cookies.py [путь] [--fix]
"""
import re
import shutil
import sys
import warnings
from http.cookiejar import MozillaCookieJar

DEFAULT_PATH = "/root/musicBot/cookies.txt"


def fix_separators(path: str) -> int:
    """Заменяет группы пробелов на табы. Возвращает число исправленных строк."""
    lines = open(path, encoding="utf-8").read().splitlines()
    out, fixed = [], 0

    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        fields = re.split(r"\s{2,}", line.strip())
        if len(fields) == 7:
            out.append("\t".join(fields))
            fixed += 1
        else:
            out.append(line)

    if fixed:
        shutil.copy(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
    return fixed


def load(path: str):
    jar = MozillaCookieJar(path)
    # stdlib печатает собственный traceback при разборе битого формата —
    # глушим его, у нас есть своё понятное сообщение.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        jar.load(ignore_discard=True, ignore_expires=True)
    return jar


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else DEFAULT_PATH
    do_fix = "--fix" in sys.argv

    try:
        jar = load(path)
    except Exception as e:
        if "Netscape format" not in str(e):
            print(f"❌ Не удалось прочитать {path}: {e}")
            return 1

        print("❌ Файл не в формате Netscape (обычно — пробелы вместо табов).")
        if not do_fix:
            print("   Запустите с флагом --fix, чтобы исправить разделители автоматически:")
            print(f"   python3 {sys.argv[0]} {path} --fix")
            return 1

        fixed = fix_separators(path)
        if not fixed:
            print("   Не удалось разобрать ни одной строки — выгрузите cookies заново.")
            return 1
        print(f"🔧 Исправлено строк: {fixed} (бэкап: {path}.bak)")
        try:
            jar = load(path)
        except Exception as e2:
            print(f"❌ После исправления файл всё ещё не читается: {e2}")
            return 1

    if [c for c in jar if c.name == "media-user-token" and c.domain == ".music.apple.com"]:
        print("✅ Файл в порядке: media-user-token найден (домен .music.apple.com).")
        return 0

    print("❌ Токен не найден в нужном виде.")
    wrong_domain = [c for c in jar if c.name == "media-user-token"]
    if wrong_domain:
        print(
            f"   media-user-token есть, но домен = '{wrong_domain[0].domain}' "
            f"(gamdl требует ровно '.music.apple.com')"
        )
    else:
        names = sorted({c.name for c in jar})
        print(f"   Всего cookies: {len(names)}. media-user-token среди них нет.")
        print(f"   Имена: {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
    print("\nПодсказка: выгружайте cookies, находясь на сайте music.apple.com и будучи залогиненным.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
