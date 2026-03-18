# Repository Guidelines

## Project Structure & Module Organization
The Git repository root is `miyoushe-tool/`. Keep backend code in `backend/app`, backend tests in `backend/tests`, and the Vue admin UI in `frontend/src`. Runtime SQLite files live under `data/`, while `docs/` stores feature notes and roadmap material. Do not commit local artifacts such as `frontend/dist/`, `node_modules/`, `.venv*/`, Playwright logs, or `*.db` files.

## Build, Test, and Development Commands
Backend setup and run:
```powershell
cd backend
python -m venv .venv313
.\.venv313\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Backend verification:
```powershell
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
.\.venv313\Scripts\python.exe -m compileall app
```
Frontend development:
```powershell
cd frontend
npm install
npm run dev
npm run build
```
Use `docker compose up -d --build` from the repo root for the full stack.

## Coding Style & Naming Conventions
Use 4-space indentation in Python and 2-space indentation in Vue/TypeScript. Follow existing naming: `snake_case` for Python modules and functions, `PascalCase` for Vue components and view files such as `AdminUsers.vue`, and descriptive store/api names such as `user.ts` or `index.ts`. Preserve the repository’s Chinese maintenance comments when changing business-critical logic, especially around sign-in flow, timezone handling, and compatibility fallbacks.

## Testing Guidelines
Backend tests use `unittest` and follow the `test_*.py` pattern. Add or extend tests in `backend/tests` when changing API behavior, login-state maintenance, scheduling, or gacha logic. There is no dedicated frontend test suite yet; at minimum, run `npm run build` and include manual verification notes for UI changes.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commits, for example `feat(自动签到调度): ...` and `fix(签到适配): ...`. Keep the format `type(scope): subject`, with focused scopes. For this repository, do not add personal information to commits, including real names, email addresses, `Co-authored-by` trailers, or signature-style footers. PRs should describe the user-visible change, list verification commands, mention any SQLite compatibility impact, and include screenshots for frontend updates.

## Security & Configuration Tips
Never hardcode secrets; use `.env` or Docker environment variables. Changes to sign-in parameters, SMTP layering, or database schema must keep backward compatibility in mind because the project does not use Alembic migrations.
