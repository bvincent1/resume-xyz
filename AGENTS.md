# AGENTS.md

Personal resume / job-application toolkit. Three independent subprojects, no root workspace or root `package.json`: a Django admin app, an Express PDF renderer, and a Cloudflare redirect worker.

## Layout
- `application_manager/` — Django 5.1 admin-only app (the main project). Entrypoint `application_manager/manage.py`; settings module `application_manager.settings`; `/` redirects to `/admin/`. Custom user `accounts.CustomUser` (email login, `AUTH_USER_MODEL`).
- `json-resume-api/` — Express 5 + puppeteer. `POST /resume/pdf` renders a JSON Resume object to a PDF under `public/`; `POST /resume/html` writes the rendered HTML document instead. `src/index.js` renders through the local `theme/` Handlebars package (`require('../theme')`).
- `cf-redirect-worker/` — Cloudflare Worker (TypeScript + wrangler + Hyperdrive). Redirects `*.deuterium.dev` and logs query strings to Postgres table `tracking.cloudflare_logs`.

### Django commands (run in `application_manager/`)
- `make install` — `poetry install`.
- `make dev` — runserver on `0.0.0.0:9099` (Makefile overrides `settings.runserver.default_port`, which is 8099).
- `make migrations` — `makemigrations accounts`, `makemigrations job_applications`, then `migrate`.
- `make seed` — migrations + `createsuperuser --no-input --email admin@admin.ca` (needs `DJANGO_SUPERUSER_PASSWORD`).
- `make worker` / `make scheduler` — Celery (RabbitMQ broker from `RABBITMQ_CLIENT_HOST`/`RABBITMQ_CLIENT_PORT`); broker config is in `application_manager/application_manager/celery.py`.
- `make pdfs` (`generate_pdfs`) / `make prompts` (`regen_prompts`) — management commands.
- `make backup` — `pg_dump` using `DB_CONNECTION`.
- Tests: `poetry run python manage.py test` (both `tests.py` files are empty stubs).
- Requires `application_manager/.env` (the Makefile does `include .env`).

### json-resume-api (run in `json-resume-api/`)
- `make install` → `pnpm install`; `make dev` → `nodemon src/index.js`; `make test` → `pnpm test`; `make clean` → delete generated `public/*.pdf` and `public/*.html`.
- `pnpm test` (or `make test`) runs the route tests in `test/` with Node's built-in test runner. `theme/index.test.js` still needs `jest` + `html-validate`, which are not dependencies, and is not picked up by the test script.

### cf-redirect-worker (run in `cf-redirect-worker/`)
- `make install`; `make types` → `wrangler types`; `make deploy`; `make dev` requires a root `.env` to build the Hyperdrive local connection string.
- `pnpm test` (vitest) runs `test/index.spec.ts`, which still asserts the scaffold `"Hello World!"` snapshot and does not match the current redirect behavior.

## Env / tooling gotchas
- No root `.env` exists. The root `Makefile` and `cf-redirect-worker/Makefile` (`include ../.env`) need one — copy `.env.example`. `application_manager/.env` is separate and untracked.
- `.env.example` documents `DATABASE_URL`, but Django reads `POSTGRES_URL` (default `postgres://postgres:postgres@localhost:5459/postgres`). Env vars referenced in Django code: `POSTGRES_URL`, `RABBITMQ_CLIENT_HOST/PORT`, `RESUME_SERVICE_HOST` (base URL of the `json-resume-api`), `STORAGE_HOST/REGION/ACCESS_KEY/SECRET_KEY`, `CHROME_URL/CHROME_TOKEN`.
- `Application.notes` has a field default that reads `supporting_documents/1st_interview_questions.md` from the local filesystem via `settings.BASE_DIR` at import time (no longer CWD-dependent).
- `.python-version` says 3.13.0 but `.tool-versions`, `pyproject.toml`, and `Dockerfile.python` use 3.12.

## Known WIP gaps (verify before relying on these paths)
- `build_pdf()` and prompt generation read `json-resume.json` and `supporting_documents/*` from the local filesystem under `application_manager/application_manager/`; the Jinja `templates/*` are still loaded from S3 via `FileService`, so the bucket must contain them.
- `job_applications/admin.py` and the `get_job_urls` command shell out to a `scraper/` Node project that is not in this repo.
