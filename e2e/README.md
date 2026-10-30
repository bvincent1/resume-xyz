# E2E tests

Playwright happy-path test for the Django admin. It uses a disposable
Postgres database and the real `json-resume-api` renderer, with AI and company
research stubbed at the external boundaries.

## Prerequisites

- Docker with Compose
- pnpm
- Poetry environment for `application_manager/`

## Run

```bash
cd e2e
make install      # install Playwright test package
make browsers     # download Chromium
make test
```

Useful targets:

- `make test-headed` — run with a visible browser
- `make down` — stop the E2E containers
- `make up` — start only Postgres and the PDF renderer
- `make migrate` / `make seed` — prepare the E2E database manually

## Ports

The dev stack uses 3000 (PDF renderer), 5672/15672 (RabbitMQ), and 9099
(Django). The E2E stack therefore uses:

- PDF renderer: `3001`
- Postgres: `55432`
- Django (test runserver): `8099`

This lets both stacks run at the same time.
