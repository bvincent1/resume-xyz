# Plan: Playwright happy-path test for company research

Status: implemented in `ba8d7b9c`.

## Goal

One browser test that:

1. Creates an `Application` through the Django/Unfold admin.
2. Triggers company research and verifies the brief and timestamp are persisted and visible.
3. Triggers the tuning pipeline and verifies the AI output was persisted with no prompt error.
4. Builds a PDF and verifies the renderer returned a PDF URL without parsing PDF bytes.

The test verifies the app's orchestration and admin UI. LLM and TinyFish output are
deterministic stubs, so the test does not depend on model quality, API keys, or network
access.

## Architecture

```text
Playwright (Chromium)
   │
   ▼
Django admin on 127.0.0.1:8099
   │  settings_e2e.py
   │  Celery eager mode
   ├─► Fake TinyFish client      → real build_company_brief / ensure_company_research
   ├─► Fake pydantic-ai Agent    → real run_tuning / merge / validate / persist
   └─► Real json-resume-api      → PDF file + URL
```

Django runs with test-specific settings and startup stubs. Nothing is patched in
production settings.

## Files

| File | Purpose |
|---|---|
| `e2e/package.json` | `@playwright/test` dependency and scripts |
| `e2e/playwright.config.ts` | Chromium project, base URL, traces, auth setup |
| `e2e/tests/application-happy-path.spec.ts` | The happy-path test |
| `e2e/tests/auth.setup.ts` | Logs in once and saves `storageState` |
| `e2e/docker-compose.yaml` | Disposable Postgres and `json-resume-api` |
| `e2e/Makefile` | Test, setup, and compose targets |
| `application_manager/application_manager/settings_e2e.py` | E2E DB and eager Celery config |
| `application_manager/application_manager/e2e_server.py` | `django.setup()`, install stubs, runserver |
| `application_manager/application_manager/e2e_stubs.py` | Fake TinyFish client and fake agent |
| `application_manager/job_applications/management/commands/seed_e2e.py` | Seeds superuser, provider, and status |

Playwright artifacts under `.auth/`, `test-results/`, and `playwright-report/` are
gitignored.

## Test environment

`settings_e2e.py` uses a dedicated database and runs Celery synchronously:

```python
DATABASES = {
    "default": dj_database_url.config(
        env="E2E_POSTGRES_URL",
        default="postgres://postgres:postgres@127.0.0.1:55432/resume_e2e",
        conn_max_age=0,
    )
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
```

Eager mode means the admin actions complete inside the request. The test needs no
RabbitMQ, no worker, and no polling.

`e2e_stubs.py` replaces only external boundaries:

- `tinyfish.TinyFish` returns fixed search and fetch results. This still exercises the
  real brief formatting, truncation, and persistence.
- `ai.build_agent` returns a full valid JSON Resume document.

The fake agent asserts that research reached the pipeline:

```python
class _FakeAgent:
    def run_sync(self, prompt, deps=None):
        if RESEARCH_MARKER not in (deps.company_research or ""):
            raise AssertionError("company research missing from pipeline deps")
        return SimpleNamespace(output=self.output)
```

`e2e_server.py` installs the stubs after `django.setup()` and runs with `--noreload`,
so the autoreloader cannot replace the patched process.

## Test flow

### Setup and auth

`auth.setup.ts` logs in through `/admin/login/?next=/admin/` and writes
`.auth/admin.json`. The main project depends on the setup project and reuses that
storage state.

### 1. Add an application

Navigate to `/admin/job_applications/application/add/` and fill:

- Company: `Acme E2E`
- Title: `Senior Engineer E2E`
- Description: `Build deterministic things.`
- Provider: `e2e-provider`

`Description` uses Unfold's Trix widget, so fill the contenteditable editor rather than
the hidden input:

```ts
const description = page.locator('trix-editor[input="wysiwyg-description"]');
await description.fill("Build deterministic things.");
await description.blur();
```

Click **Save and continue editing**, assert the success message, and capture the
application id from the change URL.

### 2. Refresh company research

Click the **Refresh company research** detail action and assert the redirect message.
Because Celery is eager, the work has already completed.

Return to the change page, open the **Metadata** tab, and assert:

```ts
await expect(page.getByText(/E2E research marker/)).toBeVisible();
await expect(
  page
    .getByText("Company researched at:")
    .locator("xpath=ancestor::div[contains(@class, 'field-line')]")
).toContainText(/\d{4}/);
```

### 3. Regenerate prompts / AI

Click **Regenerate prompts**. Assert the redirect message, reopen the application,
open the **Extra** tab, and click the `tuning` link.

On the `Prompt` page, assert:

```ts
await expect(page.locator("#id_error")).toHaveValue("");

const response = JSON.parse(
  await page.locator("#id_response").inputValue()
);
expect(response.basics.summary).toBe("E2E tuned summary");
```

Also assert the prompt description contains `Acme E2E`, confirming it was built for
the right application.

### 4. Build the PDF

**Build PDF** is a `target="_blank"` detail action. Click it, capture the popup, and
poll the change form until `resume_url` is persisted. Then fetch the saved URL:

```ts
await expect
  .poll(async () => {
    await page.goto(changeUrl);
    return page.locator("#id_resume_url").inputValue();
  }, { timeout: 30_000, intervals: [500, 1_000, 2_000] })
  .toMatch(/\.pdf$/);

const resumeUrl = await page.locator("#id_resume_url").inputValue();
expect((await page.request.get(resumeUrl)).status()).toBe(200);
```

Do not parse the PDF. The assertion is only that the renderer returned and served a
PDF URL.

## Selector notes and gotchas

- Prefer accessible locators: `getByLabel`, `getByRole`, `getByText`.
- Unfold tabs are anchors without `href`; use `page.locator("a", { hasText: "Metadata" })`
  rather than `getByRole("tab")`.
- Readonly fields do not consistently expose `.field-<name>` classes; assert their text
  or find the surrounding `.field-line`.
- The `description` field is a Trix editor with a `wysiwyg-description` input id.
- `datetime` values use the local timezone; assert a year-shaped value, not an exact time.
- `Build PDF` opens a new page because of `target="_blank"`.
- Use `workers: 1` with a disposable database; the test mutates global admin data.
- Do not use `application_manager/Makefile` for E2E. It includes `.env` and targets
  the configured Neon database.

## Playwright configuration

```ts
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://127.0.0.1:8099",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: ".auth/admin.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command:
      "cd ../application_manager && " +
      "E2E_STUBS=1 TINYFISH_API_KEY=e2e " +
      "E2E_POSTGRES_URL='...' RESUME_SERVICE_HOST='http://127.0.0.1:3001' " +
      "poetry run python -m application_manager.e2e_server",
    url: "http://127.0.0.1:8099/admin/login/",
  },
});
```

## Running it

The E2E stack uses separate ports so it can run alongside the dev stack:

| Service | Dev | E2E |
|---|---:|---:|
| PDF renderer | `3000` | `3001` |
| Postgres | — | `55432` |
| Django | `9099` | `8099` |
| RabbitMQ | `5672` / `15672` | not needed |

From `e2e/`:

```bash
make install
make browsers
make test
```

`make test` starts the compose services, migrates, flushes and seeds the E2E database,
then runs Playwright. Use `make test-headed` for a visible browser and `make down` to
stop the containers.

## Out of scope

- Verifying PDF contents or layout.
- Testing real TinyFish search quality or real LLM output quality.
- Testing Celery retries or failure paths.
- Parallel test execution or multiple application records.

Those can be separate live/integration suites later. This plan keeps the happy path
deterministic and CI-safe.
