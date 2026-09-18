# 米游社自动签到 Web 平台 (Miyoushe Tool) - Gemini Context

This document serves as the primary instructional context for Gemini CLI when working on this project. It takes precedence over general workflows.

## Project Overview

A comprehensive account management and automation platform for miHoYo (Miyoushe) games, including Genshin Impact, Honkai: Star Rail, Honkai Impact 3rd, and Zenless Zone Zero.

- **Architecture:** Monorepo with a FastAPI backend and a Vue 3 frontend.
- **Core Technologies:**
  - **Backend:** Python 3.13, FastAPI, SQLAlchemy (Async), MySQL 8, APScheduler, Playwright (for QR login), Pydantic v2.
  - **Frontend:** Vue 3 (Script Setup), Vite, TypeScript, Element Plus, Pinia.
  - **Deployment:** Docker Compose (Nginx + Python + MySQL 8).
- **Key Features:** Passport high-privilege login, automated/scheduled sign-ins, and email notifications.

## Technical Mandates

### 1. Environment & Database
- **MySQL Only:** The project has dropped SQLite support. All database interactions must use `mysql+asyncmy://`.
- **Timezone:** Strictly use `Asia/Shanghai` (UTC+8) for business dates, API datetime output, logs, and scheduled tasks. Do not add an `APP_TIMEZONE` setting, and do not format frontend times in the browser's local timezone. Database `DateTime` values remain naive UTC instants; JWT `exp` remains UTC.
- **Encryption:** `ENCRYPTION_KEY` must be persistent. If missing in `.env`, the system generates a random one at runtime, which will break existing encrypted cookies upon restart.

### 2. Backend Conventions (Python/FastAPI)
- **Directory:** `backend/`
- **Dependency Management:** `requirements.txt`. Use a virtual environment (e.g., `.venv313`).
- **Async First:** All database and I/O operations must be `async`. Use `async_session` from `app.database`.
- **Models & Schemas:** SQLAlchemy models are in `app/models/`, and Pydantic schemas are in `app/schemas/`.
- **Services Layer:** Business logic belongs in `app/services/`.
- **Testing:** Use `unittest`. A dedicated `TEST_DATABASE_URL` (MySQL) is required. Never use the production database for tests.

### 3. Frontend Conventions (Vue/TS)
- **Directory:** `frontend/`
- **Style:** Vue 3 `<script setup>` with TypeScript. Use Element Plus for UI components.
- **State Management:** Pinia.
- **API Calls:** Use the centralized axios instance in `src/api/`.
- **Routing:** Vue Router.

## Building and Running

### Development
- **Backend:**
  ```powershell
  cd backend
  python -m venv .venv313
  .\.venv313\Scripts\activate
  pip install -r requirements.txt
  uvicorn app.main:app --reload
  ```
- **Frontend:**
  ```powershell
  cd frontend
  npm install
  npm run dev
  ```

### Testing
- **Backend:**
  ```powershell
  cd backend
  # Ensure TEST_DATABASE_URL is set in environment
  python -m unittest discover -s tests -v
  ```
- **Frontend:**
  ```powershell
  cd frontend
  npm run test # Runs specific test scripts via node
  ```

### Deployment (Docker)
```powershell
docker compose up -d --build
```

## Key Files
- `backend/app/main.py`: Application entry point and lifespan management.
- `backend/app/config.py`: Configuration handling via Pydantic Settings.
- `backend/app/database.py`: SQLAlchemy engine and session setup.
- `frontend/src/api/index.ts`: Centralized API client.
- `docker-compose.yml`: Production orchestration.
- `docs/roadmap/`: Future feature plans. Current direction is the self-hosted Miyoushe sign-in platform, see `docs/roadmap/2026-09-19-github-mihoyo-feature-recommendations.md`.

## Development Guidelines
- **Security:** Never commit `.env` files. Protect `ENCRYPTION_KEY` and `SECRET_KEY`.
- **Sign-in Logic:** Sign-in requests must include proper `DS` (Dynamic Secret), `User-Agent`, and device headers (`x-rpc-device_id`, `x-rpc-device_fp`) to avoid risk triggers.
- **Code Style:** Follow existing patterns for service instantiation and dependency injection (mostly manual via session passing).
