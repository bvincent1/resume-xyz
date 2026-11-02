# Job automation module

Status: implemented.

## Goal

A `job_automation` app that turns a job-posting URL into a filled-in `Application`, then lets
`Application.save()` drive the existing research and resume-tuning tasks.

```
POST /api/job-automation/job-urls/   (X-API-Key)
        │  JobURL.objects.get_or_create(...)  →  save()
        │      └─ on_commit → dispatch_scan
        ▼
scan_job_url_task (celery)
        │  TinyFish agent.run(goal, url, output_schema=JobPosting)
        │  → Application.objects.create/refresh(title, company, description, job_url, provider)
        │      └─ save() → on_commit → chain(research → tuning)
        └─ JobURL: status="done", application=app   (or status="failed", error=…)
```

## Decisions

| Topic | Decision |
| --- | --- |
| App package | `job_automation/`, `JobAutomationConfig`, label `job_automation` |
| Models | Move `URLStatus` + `JobURL` as-is; keep the names (no rename churn) |
| API framework | DRF (`djangorestframework` is already installed and in `INSTALLED_APPS`) — no new dependency |
| API key | `X-API-Key` header vs `settings.JOB_AUTOMATION_API_KEY` (env-sourced) |
| Provider for the created application | `PromptProvider.objects.order_by("name").first()` |
| Scan semantics | One `Application` per `JobURL`; a forced rescan refreshes the linked application |
| Extraction | TinyFish `client.agent.run(..., output_schema=…)` — one call, structured JSON |
| Scan trigger | `JobURL.save()` queues the scan when the URL is new and status is `todo` |
| Trigger | `Application.save()` queues `chain(research → tuning)` when title/company/description change |

## 1. New app

```
job_automation/
├── __init__.py
├── apps.py
├── models.py
├── admin.py
├── views.py                          # API key auth + serializer + view
├── urls.py
├── tasks.py                          # TinyFish scan + task
├── tests.py
├── migrations/
│   ├── __init__.py
│   ├── 0001_initial.py
│   └── 0002_joburl_scan_fields.py
└── management/commands/get_job_urls.py
```

```python
# apps.py
class JobAutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "job_automation"
```

## 2. Move `URLStatus` + `JobURL`

`job_automation/models.py`:

```python
class URLStatus(models.Model):
    name = models.CharField(blank=False, null=False)
    def __str__(self): return self.name


class JobURL(models.Model):
    url = models.URLField(unique=True, blank=False, null=False)
    status = models.ForeignKey(URLStatus, on_delete=models.PROTECT)
    application = models.OneToOneField(
        "job_applications.Application",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="job_url_record",
    )
    error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "job_applications_joburl"   # reuse the existing table
```

`URLStatus` also sets `db_table = "job_applications_urlstatus"`. `application` and `error` are the
only additions; they make the scan idempotent and surface failures in the admin. Delete both models
from `job_applications/models.py`.

`JobURL.save()` owns the scan kickoff:

```python
def save(self, dispatch: bool = True, **kwargs):
    scan = (
        dispatch
        and self._url_changed()
        and self.application_id is None
        and self.status_id is not None
        and self.status.name == "todo"
    )
    super().save(**kwargs)
    if scan:
        from .tasks import dispatch_scan
        transaction.on_commit(lambda: dispatch_scan(self.pk))
```

`_url_changed()` mirrors `Application._prompt_inputs_changed()`: creation is always a change, later
saves compare against the stored URL. Status/application updates from the scan therefore never
re-trigger it.

Migrations keep the existing rows by reusing the old tables:

1. `job_automation/0001_initial.py` — `SeparateDatabaseAndState(database_operations=[], state_operations=[CreateModel URLStatus, CreateModel JobURL])`.
   Depends on `job_applications/0039_promptprovider_model`.
2. `job_automation/0002_joburl_scan_fields.py` — plain `AddField("joburl", "application", …)` and
   `AddField("joburl", "error", …)` (real `ALTER TABLE`, normal constraint names).
3. `job_applications/0040_delete_job_url_models.py` — `SeparateDatabaseAndState(database_operations=[], state_operations=[DeleteModel JobURL, DeleteModel URLStatus])`,
   depending on `job_automation/0002`.

No cycle: `0039 → job_automation/0001 → 0002 → job_applications/0040`. Verify with
`makemigrations --check` and by confirming row counts before/after a `migrate` on a DB copy.

## 3. Admin

Move `URLStatusAdmin` and `JobURLAdmin` into `job_automation/admin.py` (drop them, and their imports,
from `job_applications/admin.py`).

Replace the old `get_job_info` action — it shells out to a `scraper/` project that is not in this
repo — with scan actions:

- `list_display = ("__str__", "url", "status", "application")`, `readonly_fields = ("application", "error")`
- `list_filter` on `status`
- action **Scan selected URLs** and detail action **Scan now** → `scan_job_url_task.delay(pk, force=True)`

## 4. API endpoint

`views.py` holds the auth, the serializer and the view (no extra files for one route):

```python
class APIKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        expected = settings.JOB_AUTOMATION_API_KEY
        supplied = request.headers.get("X-API-Key", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            raise AuthenticationFailed("Invalid API key.")
        return (None, None)

    def authenticate_header(self, request):
        return "X-API-Key"          # makes failures 401, not 403


class JobURLInputSerializer(serializers.Serializer):
    url = serializers.URLField()


class JobURLView(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = []

    def post(self, request):
        data = JobURLInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        status, _ = URLStatus.objects.get_or_create(name="todo")
        job_url, created = JobURL.objects.get_or_create(
            url=data.validated_data["url"], defaults={"status": status}
        )
        if not created:
            return Response({"detail": "already exists", "id": job_url.pk}, status=409)
        return Response({"id": job_url.pk, "url": job_url.url, "status": job_url.status.name}, status=201)
```

`urls.py`: `path("job-urls/", JobURLView.as_view(), name="job-url-create")`.
Root `urls.py`: `path("api/job-automation/", include("job_automation.urls"))` before the catch-all redirect.

- Unset `JOB_AUTOMATION_API_KEY` disables the endpoint (401); it never accepts a blank key.
- Duplicate URL returns 409 without enqueuing a second scan.

## 5. TinyFish scan

Everything lives in `tasks.py`; no separate service module for ~40 lines.

```python
class JobPosting(BaseModel):
    title: str
    company: str
    description: str


class JobScanError(Exception):
    pass


def scan_posting(url: str) -> JobPosting:
    client = TinyFish(api_key=os.environ["TINYFISH_API_KEY"], timeout=120)
    response = client.agent.run(
        goal="Extract the role title, the hiring company, and the full job description verbatim.",
        url=url,
        output_schema=JobPosting.model_json_schema(),
    )
    if response.status != "COMPLETED" or not response.result:
        raise JobScanError(str(response.error) if response.error else "scan failed")
    return JobPosting.model_validate(response.result)


def default_provider() -> PromptProvider:
    provider = PromptProvider.objects.order_by("name").first()
    if provider is None:
        raise JobScanError("No PromptProvider configured.")
    return provider


def dispatch_scan(job_url_id: int) -> None:
    try:
        scan_job_url_task.delay(job_url_id)
    except Exception:
        logger.warning("could not dispatch scan for job url %s", job_url_id, exc_info=True)


@shared_task
def scan_job_url_task(job_url_id: int, force: bool = False):
    job_url = JobURL.objects.get(pk=job_url_id)
    if job_url.application_id and not force:
        return
    try:
        posting = scan_posting(job_url.url)
        provider = default_provider()
        if job_url.application_id:
            application = job_url.application
            application.title = posting.title
            application.company = posting.company
            application.description = posting.description[:20_000]
            application.job_url = job_url.url
            application.provider = provider
            application.save()
        else:
            application = Application.objects.create(
                title=posting.title,
                company=posting.company,
                description=posting.description[:20_000],
                job_url=job_url.url,
                provider=provider,
            )
    except Exception as exc:
        job_url.status, _ = URLStatus.objects.get_or_create(name="failed")
        job_url.error = str(exc)
        job_url.save(update_fields=["status", "error"])
        raise
    job_url.application = application
    job_url.status, _ = URLStatus.objects.get_or_create(name="done")
    job_url.error = None
    job_url.save(update_fields=["application", "status", "error"])
```

`JobURL.save()` dispatches the scan (`transaction.on_commit`), so the API view, the admin and scripts all
queue it by creating a row. Guards: the URL must be new, `status` must be `todo`, and no application may
already be linked. `save(dispatch=False)` opts a caller out (used by the bulk `get_job_urls` import).
`force=True` bypasses the linked-application check and refreshes the existing application instead of
creating a second one; the admin actions use it.

- `TinyFish` is imported inside the function (same pattern as `ai.py`) so tests can patch
  `tinyfish.TinyFish`.
- No Celery retry: the failure is persisted on the `JobURL` and retried from the admin action.
- Status rows are `get_or_create`d, so no seed data is needed (`todo`, `done`, `failed`).
- `Application.objects.create(...)` is the hand-off; its `save()` queues the pipeline.

## 6. `Application.save()` dispatch

`job_applications/models.py` — enable the existing commented-out dispatch:

```python
def save(self, **kwargs):
    dispatch = (
        self._prompt_inputs_changed()
        and bool(self.company)
        and bool(self.description)
    )
    super().save(**kwargs)
    if dispatch:
        from .tasks import dispatch_application_pipeline
        transaction.on_commit(lambda: dispatch_application_pipeline(self.pk))
```

`job_applications/tasks.py` — replace the now-unused `dispatch_generate_prompts`:

```python
from celery import chain

def dispatch_application_pipeline(application_id: int) -> None:
    """Research the company, then refine the resume."""
    try:
        chain(
            generate_company_brief.si(application_id),
            generate_prompts.si(application_id),
        ).apply_async()
    except Exception:
        logger.warning("could not dispatch pipeline for application %s", application_id, exc_info=True)
```

The chain guarantees research is persisted before tuning, which would otherwise crawl the company
itself via `ensure_company_research()`. No loop: `company_research`, `tuning` and `resume_url` saves
do not change `description`/`title`/`company`, so they never re-dispatch. The scan's `create()` is the
only new entry point.

## 7. Wiring

- `settings.py`: add `"job_automation"` to `INSTALLED_APPS` (after `job_applications`); add
  `JOB_AUTOMATION_API_KEY = os.getenv("JOB_AUTOMATION_API_KEY", "")`.
- `application_manager/celery.py`: add `"job_automation"` to `app.autodiscover_tasks([...])`.
- `application_manager/urls.py`: include the new URLconf.
- `Makefile`: add `makemigrations job_automation` to `migrations` and `job_automation` to `tests`.
- Move `job_applications/management/commands/get_job_urls.py` to `job_automation/management/commands/`
  and point its imports at `job_automation.models` (it still shells out to the missing `scraper/`).
- `.env`: add `JOB_AUTOMATION_API_KEY`. No new dependencies.

## 8. Integration test

One test class in `job_automation/tests.py`; no unit tests. Real request → Celery task → ORM, with
only the external boundaries stubbed.

```python
@override_settings(
    JOB_AUTOMATION_API_KEY="test-key",
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class JobAutomationIntegrationTests(TransactionTestCase):
```

`TransactionTestCase` so `transaction.on_commit` callbacks (the view's enqueue and `save()`'s chain)
actually run.

Setup and stubs:

- One `PromptProvider(env_key="TEST_PROVIDER_KEY")`.
- `patch("tinyfish.TinyFish", FakeTinyFish)`: `agent.run` returns
  `AgentRunResponse(status="COMPLETED", result={"title", "company", "description"}, num_of_steps=1)`;
  `search.query` / `fetch.get_contents` return one page containing a research marker (same shape as
  `application_manager/e2e_stubs.py`).
- `patch("job_applications.ai.build_agent", …)` returns a fake agent holding a valid `ResumeDocument`
  and asserts `deps.company_research` contains the marker (proves research ran first).
- `patch.dict(os.environ, {"TINYFISH_API_KEY": "test", "TEST_PROVIDER_KEY": "secret"})`.

Cases:

1. **Happy path** — `POST` with `X-API-Key: test-key` and `{"url": "https://jobs.test/123"}` returns
   201; one `JobURL` with `status="done"`, `application` set, `error=None`; the `Application` has the
   extracted title/company/description, `job_url`, and the provider; `company_research` contains the
   marker with `company_researched_at` set; `application.prompt.response` is populated with no `error`.
2. **Auth** — missing/wrong key returns 401 and creates no `JobURL`.
3. **Scan failure** — `agent.run` returns `status="FAILED"`; `JobURL.status == "failed"`, `error` is
   set, and no `Application` exists.
4. **Forced rescan** — after the happy path, `scan_job_url_task(pk, force=True)` with different scan
   output updates the linked `Application` in place (`Application.objects.count() == 1`) and re-runs the
   save-time pipeline.

Run with `poetry run python manage.py test job_automation`.

## Not doing

- A key table or token model; one env-var key is enough.
- Extra endpoints (list/detail/delete) or OpenAPI docs.
- Retrying scans in Celery; the admin action re-runs them.
- Prompt/agent tuning for the scan; TinyFish owns extraction.

## Risks

1. **Migration ordering** across apps is the delicate part; verify with `makemigrations --check` and on
   a DB copy. The `db_table` names keep the legacy `job_applications_*` prefix.
2. **Cost** — each scan is one TinyFish run, one company crawl and one LLM tuning call; enabling
   `save()` dispatch also means editing description/title/company in the admin spends tokens.
3. **Latency** — `agent.run` can take tens of seconds; keep the Celery time limit above the 120s
   client timeout.
4. **Provider is implicit** (alphabetically first); log the chosen name in the scan task.
