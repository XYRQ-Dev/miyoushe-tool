# Repository Guidelines

## Project Structure & Module Organization
The repository is split into `backend/` and `frontend/`. Put FastAPI code in `backend/app`, backend tests in `backend/tests`, and helper scripts in `backend/scripts`. The Vue 3 admin UI lives in `frontend/src`, with views under `frontend/src/views`, shared components under `frontend/src/components`, and theme assets under `frontend/src/styles`. Keep long-form notes in `docs/`. Do not commit local runtime output such as `frontend/dist/`, `.venv*`, `.playwright-cli/`, `.superpowers/`, `output/`, or ad hoc database files.

## Build, Test, and Development Commands
Backend local run:
```powershell
cd backend
.\.venv313\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Backend checks:
```powershell
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
.\.venv313\Scripts\python.exe -m compileall app
```
Frontend local run:
```powershell
cd frontend
npm install
npm run dev
npm test
npm run build
```
Use `docker compose up -d --build` from the repo root when you need the full stack.

## Coding Style & Naming Conventions
Use 4 spaces in Python and 2 spaces in Vue/TypeScript/CSS. Follow existing naming: Python modules and functions use `snake_case`; Vue components and view files use `PascalCase` such as `AdminUsers.vue`; stores and utilities use concise descriptive names such as `user.ts`. Keep Chinese maintenance comments where business rules, compatibility constraints, or failure risks are non-obvious.

## Testing Guidelines
Backend tests use `unittest` with files named `test_*.py`. Add or extend tests when changing login flows, scheduling, redeem logic, asset aggregation, or API behavior. Frontend regression checks currently run through `npm test` and type/build verification through `npm run build`. For UI-heavy changes, include brief manual verification notes for desktop, tablet, mobile, and dark mode when relevant.

## Commit & Pull Request Guidelines
Use Conventional Commits: `feat(scope): subject`, `fix(scope): subject`, `docs(scope): subject`. Keep scopes specific, for example `frontend`, `signin`, or `redeem`. PRs should summarize the user-visible change, list verification commands, note config or migration impact, and include screenshots for frontend updates.

## Security & Configuration Tips
Store secrets in `.env` or Docker environment variables; never hardcode credentials. Changes affecting sign-in parameters, SMTP settings, or database defaults must preserve existing deployments and local migration workflows.
