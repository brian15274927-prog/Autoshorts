# AI Video Studio - Project Context

## Overview
SaaS платформа для генерации AI-видео. Основные продукты:
- **Faceless AI** - генерация видео с закадровым голосом и AI-изображениями
- **Music Video Generator** - создание видеоклипов из аудио
- **Shorts** - нарезка YouTube видео (в разработке)
- **AI Portraits** - генерация портретов (в разработке)

## Tech Stack
- **Backend**: FastAPI (Python 3.11+)
- **Frontend**: Jinja2 templates + Tailwind CSS + Alpine.js
- **Database**: SQLite (с поддержкой PostgreSQL)
- **Queue**: Redis + Celery (опционально, работает и без них)
- **AI Services**: OpenAI (GPT-4o-mini, DALL-E 3), Google Gemini (Nano Banana)
- **Video**: FFmpeg, Ken Burns effect

## Project Structure
```
C:\dake\
├── app/
│   ├── api/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── routes/
│   │   │   ├── faceless.py      # Faceless video API
│   │   │   ├── musicvideo.py    # Music video API
│   │   │   └── ...
│   │   └── dependencies.py
│   ├── services/
│   │   ├── faceless_engine.py   # Main video generation engine
│   │   ├── musicvideo_service.py # Music video generation
│   │   ├── dalle_service.py     # DALL-E 3 image generation
│   │   ├── nanobanana_service.py # Gemini image generation
│   │   ├── ken_burns_service.py # Video assembly with effects
│   │   ├── audio_analyzer.py    # Audio file analysis
│   │   ├── llm_service.py       # LLM wrapper
│   │   └── agents/
│   │       ├── orchestrator.py  # Multi-agent coordination
│   │       ├── storyteller.py   # Script generation
│   │       ├── story_analyzer.py # Visual Bible creation
│   │       └── visual_director.py # Image prompt generation
│   ├── saas_ui/
│   │   ├── routes.py            # UI page routes
│   │   └── templates/
│   │       ├── base.html        # Base template (Alpine.js, Tailwind)
│   │       ├── faceless.html    # Faceless studio UI
│   │       ├── musicvideo.html  # Music video generator UI
│   │       └── ...
│   ├── auth/                    # Authentication system
│   ├── credits/                 # Credit system
│   └── persistence/             # Database repos
├── data/
│   ├── outputs/                 # Generated videos
│   ├── temp_images/             # Temporary images
│   ├── musicvideo/              # Music video files
│   └── templates/               # AI portrait templates
└── tools/
    └── ffmpeg-master-latest-win64-gpl/  # FFmpeg binaries
```

## Key Components

### 1. Multi-Agent System (Faceless)
```
User Request → Storyteller → StoryAnalyzer → VisualDirector → Image Generation → Video Assembly
```

- **Storyteller**: Creates script with segments (text, voiceover)
- **StoryAnalyzer**: Creates Visual Bible (characters, locations, style guide)
- **VisualDirector**: Generates image prompts for each segment

### 2. Image Generation
- **DALL-E 3**: High quality, native aspect ratios (1024x1792 for 9:16, 1792x1024 for 16:9)
- **Nano Banana (Gemini)**: Fast, cost-effective alternative

### 3. Video Assembly
- Ken Burns effect (pan/zoom on still images)
- FFmpeg for encoding
- Subtitle overlay with custom fonts

## Recent Changes

### Session 2026-01-08

#### Image Fixes
- Fixed aspect ratios in `dalle_service.py`:
  - 9:16 (TikTok): 1024x1792 (native vertical)
  - 16:9 (YouTube): 1792x1024 (native horizontal)
- Added aspect hints to Nano Banana prompts

#### Character Frequency
- Updated `visual_director.py` to limit characters to 30-40% of segments
- Added visual variety: landscape, object, character, atmospheric shots
- Character segments: `{0, segment_count // 3, segment_count // 2, segment_count - 2}`

#### Music Video Generator (NEW)
Created complete music video generation feature:

**Files created:**
- `app/services/audio_analyzer.py` - FFprobe audio analysis
- `app/services/musicvideo_service.py` - Main generation service
- `app/api/routes/musicvideo.py` - API endpoints
- `app/saas_ui/templates/musicvideo.html` - UI (Alpine.js + Jinja2)

**Features:**
- Audio upload (MP3, WAV, M4A, AAC, OGG, FLAC)
- Theme/lyrics input for visual matching
- Art style selection (Cinematic, Anime, Ghibli, etc.)
- Image provider choice (DALL-E 3 / Nano Banana)
- Progress tracking with SSE
- Video preview and download

**API Endpoints:**
- `POST /api/musicvideo/generate` - Start generation
- `GET /api/musicvideo/status/{job_id}` - Check progress
- `GET /api/musicvideo/stream/{job_id}` - Stream video
- `GET /api/musicvideo/download/{job_id}` - Download video

#### UI Updates
- Added Alpine.js to `base.html` for reactive UI
- Added navigation links in header: Faceless AI, Music Video, Shorts, Portraits
- Added x-cloak style for Alpine.js

## Running the Project

```bash
# Start server
cd C:\dake
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

# Access UI
http://localhost:8000/app           # Dashboard
http://localhost:8000/app/faceless  # Faceless AI
http://localhost:8000/app/musicvideo # Music Video Generator
```

## Environment Variables (.env)
```
OPENAI_API_KEY=sk-...        # Required for DALL-E and GPT
GOOGLE_API_KEY=...           # Optional for Gemini/Nano Banana
DATABASE_URL=sqlite:///...   # Database connection
```

## Known Issues / TODO
- `/app/shorts` returns 404 (not implemented)
- Portrait templates images missing (404s for .jpg files)
- Redis/Celery optional - runs in direct mode without them

## Cost Optimization
- Using `gpt-4o-mini` instead of `gpt-4o` for LLM calls
- Nano Banana (Gemini) as cheaper alternative to DALL-E
- Characters limited to 30-40% of segments to reduce image complexity

---

### Session 2026-01-08 (continued)

#### Music Video Generator - UI Simplification & Persistence

**UI Changes (musicvideo.html):**
- Removed Theme/Description field
- Removed Lyrics field
- Simplified to: Audio upload → Style selection → Provider selection → Generate
- Added "My Videos" section on the right side
- Added video modal for playback
- Two-column responsive layout

**API Changes (musicvideo.py):**
- Theme auto-generated from art_style (no user input needed)
- Added SQLite persistence (`C:\dake\data\musicvideo.db`)
- New endpoint: `GET /api/musicvideo/recent` - returns user's videos
- Thumbnail generation from video first frame
- Full CRUD: create, read, delete jobs

**Style Themes (auto-generated):**
```python
style_themes = {
    "photorealism": "Cinematic, dramatic lighting, professional photography",
    "anime": "Anime style, vibrant colors, dynamic poses",
    "watercolor": "Soft watercolor painting, flowing colors",
    "expressionism": "Abstract expressionism, bold colors",
    "ghibli": "Studio Ghibli inspired, magical, whimsical",
    "comic": "Comic book style, bold outlines, dynamic action",
    "pixel": "Pixel art, retro gaming aesthetic, 8-bit style",
    "creepy": "Dark and moody, gothic atmosphere"
}
```

**Database Schema (musicvideo_jobs):**
- job_id, user_id, audio_name, art_style, image_provider
- status, progress, output_path, thumbnail, error, created_at
