#!/usr/bin/env python3
"""
Печатает состав плейлиста Apple Music в JSON.

Запускается интерпретатором gamdl-venv: только там есть gamdl со своими
зависимостями (httpx>=0.28), которые конфликтуют с окружением бота.

Публичный iTunes Lookup API плейлисты Apple не отдаёт вовсе — отвечает 400,
поэтому используем авторизованный API gamdl с cookies аккаунта.

Использование: python apple_playlist_probe.py <cookies.txt> <playlist_id>
Результат: строка, начинающаяся с RESULT_JSON:, дальше JSON.
"""
import asyncio
import json
import sys

RESULT_PREFIX = "RESULT_JSON:"


async def main() -> int:
    from gamdl.api.apple_music import AppleMusicApi

    cookies_path, playlist_id = sys.argv[1], sys.argv[2]

    api = await AppleMusicApi.create_from_netscape_cookies(cookies_path=cookies_path)
    playlist = await api.get_playlist(playlist_id, limit_tracks=300)

    data = (playlist.get("data") or [{}])[0]
    attributes = data.get("attributes") or {}
    raw_tracks = ((data.get("relationships") or {}).get("tracks") or {}).get("data") or []

    tracks = []
    for item in raw_tracks:
        attrs = item.get("attributes") or {}
        if not item.get("id"):
            continue
        tracks.append(
            {
                "id": str(item["id"]),
                "title": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
            }
        )

    # Префикс отделяет полезную нагрузку от отладочных логов gamdl,
    # которые тоже могут попасть в stdout
    print(
        RESULT_PREFIX
        + json.dumps(
            {
                "storefront": api.storefront,
                "title": attributes.get("name", ""),
                "artist": attributes.get("curatorName", ""),
                "tracks": tracks,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
