# 🎵 KuzyMusicBot

Telegram-бот для скачивания музыки с **Qobuz** и **Spotify** с поддержкой Hi-Res аудио и распознавания треков.

## ✨ Возможности

- **⬇️ Скачивание по ссылке** — треки и альбомы с Qobuz и Spotify
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

### 6. Настрой streamrip

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

### 7. Запусти бота

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
| Загрузчик Spotify | savify |
| Распознавание | AudD.io API |
| Обработка аудио | FFmpeg |

## 📁 Структура проекта

```
musicBot/
├── main.py                  # Точка входа, регистрация хендлеров
├── config.py                # Конфигурация из .env
├── whitelist.json           # Список разрешённых пользователей
├── bot/
│   └── handlers.py          # Обработчики команд и сообщений
├── services/
│   ├── downloader.py        # Загрузка с Qobuz через streamrip
│   ├── savify_downloader.py # Загрузка со Spotify
│   ├── recognizer.py        # Распознавание аудио
│   ├── file_manager.py      # Работа с файлами
│   └── whitelist.py         # Управление whitelist
└── Qobuz/Downloads/         # Временная папка для скачивания
```

## ⚠️ Важно

- Для скачивания с Qobuz необходима **платная подписка** (Studio или Sublime)
- Токен Qobuz истекает периодически — бот уведомит когда придёт время обновить
- Файл `.env` и `whitelist.json` не попадают в репозиторий (`.gitignore`)
