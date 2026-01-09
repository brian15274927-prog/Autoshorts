# Autoshorts - AI Video Generation Platform

SaaS платформа для автоматической генерации вертикальных видео (Shorts/Reels/TikTok) с использованием AI.

## Возможности

- **Faceless Video Generation** - Создание видео без лица с AI-озвучкой и изображениями
- **Kie.ai Integration** - Генерация изображений через Nano Banana модель
- **Edge-TTS** - Профессиональная озвучка на русском и английском
- **Ken Burns Effect** - Плавная анимация изображений (zoom in/out)
- **Auto Subtitles** - Автоматические субтитры в стиле Hormozi
- **Script Editor** - Редактирование сценария с превью

## Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка окружения

```bash
cp .env.example .env
```

Ключевые настройки в `.env`:
```env
# API Keys
OPENAI_API_KEY=sk-...          # Для генерации сценариев (GPT-4)
KIE_API_KEY=...                # Для генерации изображений (Kie.ai)

# Auth
ADMIN_SECRET=your-secret-key   # Минимум 32 символа для продакшена

# Dev Mode
DEV_BROWSER_MODE=true          # Упрощённая авторизация для разработки
```

### 3. Запуск сервера

```bash
# Разработка с auto-reload
uvicorn app.api.main:app --reload --port 8000

# Продакшен
uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

### 4. Доступ к приложению

- **Faceless Generator**: http://localhost:8000/app/faceless
- **API Docs**: http://localhost:8000/docs
- **Admin UI**: http://localhost:8000/admin-ui

## Faceless Video Generation

### Процесс создания видео

1. **Выбор темы** - Введите тему или идею для видео
2. **Генерация сценария** - GPT-4 создаёт сценарий с visual prompts
3. **Редактирование** - Редактируйте текст и промпты для изображений
4. **Генерация видео** - Параллельная генерация аудио + изображений
5. **Ken Burns анимация** - Плавные переходы между кадрами
6. **Финальный рендер** - Объединение видео, аудио и субтитров

### API Endpoints

```bash
# Превью сценария
POST /api/faceless/preview-script
{
  "topic": "Интересные факты о космосе",
  "duration": 30,
  "style": "viral"
}

# Генерация видео
POST /api/faceless/generate-from-script
{
  "topic": "...",
  "duration": 30,
  "edited_segments": [...]
}

# Статус задачи
GET /api/faceless/status/{job_id}

# Скачать видео
GET /api/faceless/download/{job_id}
```

## Архитектура

```
app/
├── api/                    # FastAPI routes
│   ├── routes/
│   │   ├── faceless.py    # Faceless video endpoints
│   │   ├── god_mode.py    # Advanced editing
│   │   └── musicvideo.py  # Music video generation
│   └── main.py
├── services/
│   ├── faceless_engine.py     # Core video pipeline
│   ├── fast_script_generator.py # GPT script generation
│   ├── kie_service.py         # Kie.ai image generation
│   ├── tts_service.py         # Edge-TTS voice synthesis
│   ├── ken_burns_service.py   # Image animation
│   └── dalle_service.py       # DALL-E fallback
├── saas_ui/
│   └── templates/
│       └── faceless_mvp.html  # Main UI
├── persistence/               # SQLite repositories
├── credits/                   # Credit system
└── auth/                      # Authentication
```

## Стек технологий

- **Backend**: FastAPI, Python 3.11+
- **Database**: SQLite (async via aiosqlite)
- **Video Processing**: FFmpeg, MoviePy
- **AI Services**:
  - OpenAI GPT-4 (сценарии)
  - Kie.ai Nano Banana (изображения)
  - Edge-TTS (озвучка)
- **Frontend**: Vanilla JS, TailwindCSS

## Конфигурация

### Форматы видео

| Формат | Разрешение | Использование |
|--------|-----------|---------------|
| vertical | 1080x1920 | Shorts, Reels, TikTok |
| horizontal | 1920x1080 | YouTube |
| square | 1080x1080 | Instagram |

### Стили сценариев

- `viral` - Быстрый темп, хуки, клиффхэнгеры
- `educational` - Объяснительный стиль
- `storytelling` - Нарративный подход
- `documentary` - Документальный стиль
- `motivational` - Мотивационный контент

### Художественные стили изображений

- `photorealistic` - Фотореализм
- `cinematic` - Кинематографичный
- `anime` - Аниме стиль
- `digital_art` - Цифровое искусство
- `oil_painting` - Масляная живопись

## Тестирование

```bash
# Запуск тестов
pytest tests/ -v

# С coverage
pytest tests/ --cov=app --cov-report=html
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|-----------|----------|--------------|
| `OPENAI_API_KEY` | OpenAI API ключ | - |
| `KIE_API_KEY` | Kie.ai API ключ | - |
| `ADMIN_SECRET` | Секрет админа | `admin-secret-default` |
| `DATABASE_PATH` | Путь к SQLite | `data/app.db` |
| `DEV_BROWSER_MODE` | Dev режим | `false` |
| `DATA_DIR` | Директория данных | `./data` |

## Лицензия

MIT
