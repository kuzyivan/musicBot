# 🎵 KuzyMusicBot

Telegram-бот для скачивания музыки с **Qobuz**, **Spotify** и **Apple Music** с поддержкой Hi-Res аудио и распознавания треков.

## ✨ Возможности

- **⬇️ Скачивание по ссылке** — треки и альбомы с Qobuz, Spotify и Apple Music
- **💿 Hi-Res качество** — до 24-bit/192kHz (Qobuz Studio)
- **🎧 Распознавание музыки** — отправь голосовое или аудио, бот найдёт трек и скачает
- **📀 Выбор трека из альбома** — inline-кнопки для выбора конкретного трека
- **🖼️ Обложки** — встраиваются в файл и отправляются отдельным фото
- **🔄 Авто-конвертация** — если файл больше лимита Telegram, конвертируется в MP3 320 kbps
- **👥 Whitelist** — доступ только для разрешённых пользователей
- **🔑 Управление токеном** — обновление токена Qobuz прямо из чата

## 🤖 Команды бота

| Команда | Описание | Доступ |
|---|---|---|
| `/start` | Приветствие | Все |
| `/help` | Помощь | Все |
| `/download <ссылка>` | Скачать трек | Whitelist |
| `/users` | Список разрешённых пользователей | Админ |
| `/adduser <id>` | Добавить пользователя в whitelist | Админ |
| `/removeuser <id>` | Удалить пользователя из whitelist | Админ |
| `/settoken <токен>` | Обновить токен Qobuz | Админ |

Также можно просто отправить ссылку на трек/альбом без команды.

## 🚀 Установка

### 1. Клонируй репозиторий

```bash
git clone https://github.com/kuzyivan/musicBot.git
cd musicBot
```

### 2. Создай виртуальное окружение и установи зависимости

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Установи FFmpeg

```bash
sudo apt update && sudo apt install ffmpeg
```

### 4. Настрой `.env`

Создай файл `.env` в корне проекта:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_USER_ID=твой_telegram_user_id
ALLOWED_USERS=твой_telegram_user_id

QOBUZ_APP_ID=798273057
QOBUZ_AUTH_TOKEN=токен_из_браузера

AUDD_API_TOKEN=токен_AudD
SPOTIPY_CLIENT_ID=client_id_spotify
SPOTIPY_CLIENT_SECRET=client_secret_spotify
```

### 5. Настрой токен Qobuz

Бот использует токен сессии браузера вместо пароля (Qobuz блокирует password-авторизацию с VPS):

1. Открой [play.qobuz.com](https://play.qobuz.com) и войди в аккаунт
2. Нажми `F12` → вкладка **Network**
3. Обнови страницу (`F5`)
4. В поиске запросов найди `user/login`
5. Скопируй значение заголовка `X-User-Auth-Token`
6. Вставь в `.env` как `QOBUZ_AUTH_TOKEN=...`

Когда токен истечёт — бот сам пришлёт напоминание. Обновить можно командой `/settoken <новый_токен>` прямо в чате.

### 6. Настрой Apple Music

Нужна активная подписка Apple Music. Скачивание идёт по cookie `media-user-token` — пароль нигде не хранится.

1. Открой [music.apple.com](https://music.apple.com) в браузере, где выполнен вход
2. Выгрузи cookies расширением **Get cookies.txt LOCALLY** (Chrome) или **Export Cookies** (Firefox)
3. Положи файл как `cookies.txt` в корень проекта, права `chmod 600`

Проверить файл:

```bash
python3 check_cookies.py          # проверить
python3 check_cookies.py --fix    # заодно исправить пробелы вместо табов
```

Две вещи, о которых стоит знать заранее:

- **Качество — AAC 256 kbps.** Hi-Res (ALAC) Apple отдаёт только через wrapper-демон, которому нужно передать Apple ID и пароль — в боте это намеренно не используется.
- **Каталог ограничен регионом подписки.** Если подписка оформлена на US, треки, доступные только в других регионах, скачать нельзя ни по какой ссылке — бот сообщит об этом и предложит поискать на Qobuz.

### 7. Настрой streamrip

```bash
source venv/bin/activate
rip config open
```

В конфиге укажи:
```toml
[qobuz]
use_auth_token = true
email_or_userid = "твой_user_id_на_qobuz"
password_or_token = "токен_из_шага_5"
```

### 8. Запусти бота

```bash
python main.py
```

Или через systemd (рекомендуется для VPS):

```bash
sudo systemctl start musicbot
sudo systemctl enable musicbot
```

## 🛠️ Стек

| Компонент | Технология |
|---|---|
| Язык | Python 3.11 |
| Telegram | python-telegram-bot |
| Загрузчик Qobuz | streamrip |
| Загрузчик Spotify | spotipy (метаданные) + Qobuz или yt-dlp (файл) |
| Загрузчик Apple Music | gamdl 3.8.5 (отдельное окружение `gamdl-venv`) |
| Распознавание | AudD.io API |
| Обработка аудио | FFmpeg |

## 📁 Структура проекта

```
musicBot/
├── main.py                  # Точка входа, регистрация хендлеров
├── config.py                # Конфигурация из .env
├── check_cookies.py         # Проверка cookies.txt для Apple Music
├── cookies.txt              # Cookies Apple Music (не в репозитории)
├── whitelist.json           # Список разрешённых пользователей
├── bot/
│   └── handlers.py          # Обработчики команд и сообщений
├── services/
│   ├── sources.py           # Распознавание источника по ссылке
│   ├── downloader.py        # Загрузка с Qobuz через streamrip
│   ├── spotify_downloader.py # Загрузка по ссылке Spotify
│   ├── apple_music_downloader.py # Загрузка с Apple Music через gamdl
│   ├── recognizer.py        # Распознавание аудио
│   ├── file_manager.py      # Работа с файлами
│   └── whitelist.py         # Управление whitelist
├── AppleMusic/Downloads/    # Временная папка Apple Music
└── Qobuz/Downloads/         # Временная папка для скачивания
```

## ⚠️ Важно

- Для скачивания с Qobuz необходима **платная подписка** (Studio или Sublime)
- Токен Qobuz истекает периодически — бот уведомит когда придёт время обновить
- Для Apple Music нужна **активная подписка**; качество — AAC 256 kbps, каталог ограничен регионом подписки
- Spotify аудио не отдаёт, поэтому ссылка используется как источник метаданных: трек ищется на **Qobuz** (Hi-Res), затем на **Apple Music** (AAC 256 kbps), и лишь при отсутствии — берётся с **YouTube** через yt-dlp. В подписи всегда указывается реальный источник, а не Spotify
- Файлы `.env`, `whitelist.json`, `cookies.txt` и скачанная музыка в репозиторий не попадают (`.gitignore`)
