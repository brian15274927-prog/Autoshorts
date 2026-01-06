# Video Rendering API

SaaS API for AI-powered vertical video generation.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key settings:
- `ADMIN_SECRET` - Secret for admin authentication
- `DATABASE_PATH` - SQLite database path (default: `data/app.db`)
- `DEV_BROWSER_MODE` - Set to `true` for browser testing without headers

### 3. Start the Server

```bash
# Windows - kill any existing uvicorn processes first:
taskkill /F /IM uvicorn.exe 2>nul

# Start the server
uvicorn app.api.main:app --reload --port 8888
```

### 4. Access the Application

- **Home**: http://localhost:8888/
- **API Docs**: http://localhost:8888/docs
- **Admin UI**: http://localhost:8888/admin-ui

## Admin Web UI

The Admin UI provides a web-based interface for managing users, credits, and jobs.

### Access

1. Navigate to http://localhost:8080/admin-ui
2. Enter the `ADMIN_SECRET` from your `.env` file
3. You'll be redirected to the dashboard

### Features

- **Dashboard**: System overview with stats and recent activity
- **Users**: List, search, and manage users
- **User Detail**: View/edit user plan, adjust credits, view ledger and jobs
- **Idempotency**: View all idempotency keys with filters

### Default Admin Secret

If `ADMIN_SECRET` is not set, the default is: `admin-secret-default`

**Important**: Always set a secure `ADMIN_SECRET` in production!

## API Endpoints

### Authentication

All API endpoints require the `X-User-Id` header (except health checks).

In `DEV_BROWSER_MODE=true`, requests without headers are auto-assigned to `browser-dev-user`.

### Render Jobs

- `POST /render` - Create render job (requires `Idempotency-Key` header)
- `GET /render` - List your render jobs
- `GET /render/{task_id}` - Get job status
- `POST /render/{task_id}/cancel` - Cancel a job
- `GET /render/me/credits` - Get your credits

### Admin API

- `GET /admin/users` - List users (requires `X-Admin-Secret`)
- `POST /admin/users/{user_id}/credits` - Adjust credits

## Architecture

- **FastAPI** - Web framework
- **SQLite** - Persistence (users, credits, jobs, idempotency)
- **Celery + Redis** - Task queue for video rendering
- **MoviePy + FFmpeg** - Video processing

## Project Structure

```
app/
├── api/           # FastAPI routes and schemas
├── admin_ui/      # Admin web interface
│   ├── templates/ # Jinja2 templates
│   └── static/    # CSS
├── auth/          # Authentication middleware
├── credits/       # Credit service and job tracker
├── persistence/   # SQLite repositories
└── rendering/     # Video rendering engine
```
