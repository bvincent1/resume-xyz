# Single-call resume tuning with system-query tools

## Data model (`job_applications/models.py`)

Add to `Application`:

```python
provider = models.ForeignKey(
    "PromptProvider",
    null=False,
    blank=False,
    on_delete=models.PROTECT,
    related_name="applications",
    help_text="Model provider used for the single tuning call.",
)
tuning = models.JSONField(
    null=True,
    blank=True,
    help_text="Full JSON Resume document validated against json-resume-api/schema.json.",
)
company_research = models.TextField(
    null=True,
    blank=True,
    help_text="Cached TinyFish company brief used for tuning.",
)
company_researched_at = models.DateTimeField(null=True, blank=True)
```

Change `Prompt`:

- Remove `provider`, `parent` (and the `children` relation), and `name`.
- Change `application` to a `OneToOneField(Application, related_name="prompt")`; there is exactly one
  prompt row per application.
- Keep `description` (the rendered instruction), `template`, `response` (the raw JSON blob), `notes`, and
  `error`.
- Replace `Application.get_prompt(name)` with the `application.prompt` relation and simplify
  `Application.list_prompts()` to return the single prompt.

Add enums and resource mappings:

```python
from enum import Enum

class Company(str, Enum):
    FORTRA = "Fortra"
    BVS = "BVS"
    STAFFBASE = "Staffbase"
    TENSPD = "10SPD"

class SkillType(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATABASE = "database"
    INFRASTRUCTURE = "infrastructure"

HISTORY_PATHS = {
    Company.BVS: "supporting_documents/histories/bvs.md",
    Company.STAFFBASE: "supporting_documents/histories/staffbase.md",
    Company.TENSPD: "supporting_documents/histories/10SPD.md",
    Company.FORTRA: "supporting_documents/histories/fortra.md",
}

SKILL_PATHS = {
    SkillType.FRONTEND: "supporting_documents/frontend_skills.md",
    SkillType.BACKEND: "supporting_documents/backend_skills.md",
    SkillType.DATABASE: "supporting_documents/database_skills.md",
    SkillType.INFRASTRUCTURE: "supporting_documents/infrastructure_skills.md",
}

SKILL_TYPE_TO_RESUME_NAME = {
    SkillType.FRONTEND: "Frontend",
    SkillType.BACKEND: "Backend",
    SkillType.DATABASE: "Databases",
    SkillType.INFRASTRUCTURE: "Infrastructure",
}
```

## Tuning blob: full JSON Resume document

`Application.tuning` stores a complete JSON Resume document, not a custom section bag. It must validate
against `json-resume-api/schema.json`; a vendored copy lives at
`application_manager/application_manager/supporting_documents/json-resume.schema.json`.

The model writes tuned values into the schema's existing fields:

| Tuned content                          | JSON Resume field                       |
| -------------------------------------- | --------------------------------------- |
| Header summary                         | `basics.summary`                        |
| Company blurb per company              | `work[].summary` (matched by `name`)    |
| Skill keywords per type                | `skills[].keywords` (matched by `name`) |
| Keyword payload for the hidden section | `payload` (comma-separated string)      |

All other sections (`education`, `awards`, `certificates`, `languages`, `projects`, `meta`, etc.) are
copied from `supporting_documents/json-resume.json` unchanged.

```json
{
  "$schema": "…",
  "basics": { "name": "…", "summary": "<tuned header>" },
  "work": [{ "name": "BVS", "summary": "<tuned blurb>" }],
  "skills": [{ "name": "Frontend", "keywords": ["<tuned keyword>"] }],
  "payload": "<comma-separated keywords>"
}
```

## Resume model and validation (`job_applications/ai.py`)

- Define `ResumeDocument` as a pydantic model mirroring the schema: `$schema` (aliased), `basics`, `work`,
  `volunteer`, `education`, `awards`, `certificates`, `publications`, `skills`, `languages`, `interests`,
  `references`, `projects`, `meta`, `payload`.
- Root model uses `extra="forbid"` (matching `additionalProperties: false`); nested models use
  `extra="allow"` (matching the schema's permissive objects).
- Use `output_type=ResumeDocument` so the model receives the shape in the structured-output schema.
- After the run, merge the model output over the base resume with `merge_resume(base, patch)`:
  - deep-merge dictionaries;
  - merge `work`, `skills`, `certificates`, and other arrays by their identifying field (`name`,
    `institution`, `title`), preserving base order and keeping entries the model omitted;
  - replace scalar/list values the model did provide.
- Validate the merged document with `jsonschema.validate(blob, schema, format_checker=FormatChecker())`
  before persisting; retry the agent on failure.
- Replace the custom `TuningResult` / `JobAnalysis` models with `ResumeDocument`.

## Pipeline (`job_applications/ai.py`)

- Replace `PROMPT_SPECS` with one spec (no name field, since the prompt row is one-to-one), provider from
  `application.provider`, tools
  `("get_job_description", "get_notes", "get_history", "get_skills", "get_resume", "research_company")`.
- Remove `stage`, `parent`, `template_vars`, `_parse_parent`, `build_context`, and `run_pipeline`.
- Add `run_tuning(application_id, force=False) -> ResumeDocument`.
- Reduce `collect_inputs` to the application fields, `company`, and the cached company brief; do not read
  every supporting document up front.
- Replace `prepare_prompts` with `prepare_run(application)`, which upserts the application's single prompt
  via `Prompt.objects.update_or_create(application=application, defaults={...})`, sets `description`, and
  clears `error`.
- `build_agent(application)` builds the agent from `application.provider`; keep the per-provider model
  cache.
- On success, `run_tuning` writes the merged document to `application.tuning`, the raw JSON to
  `prompt.response`, clears `prompt.error`, and persists the company brief. On failure, set
  `prompt.error` and leave `application.tuning` unchanged.
- The provider comes from `application.provider`; remove the `STRONG_MODEL` / `CHEAP_MODEL` tier routing.

## Local resource tools (`job_applications/ai.py` or `job_applications/tools.py`)

Tools never touch the ORM; application fields are preloaded in `PipelineDeps` by `collect_inputs`.

| Tool                  | Signature                 | Returns                                             |
| --------------------- | ------------------------- | --------------------------------------------------- |
| `get_job_description` | `()`                      | `Application.description` from deps                 |
| `get_notes`           | `()`                      | `Application.notes` from deps                       |
| `get_history`         | `(company: Company)`      | `read_supporting_document(HISTORY_PATHS[company])`  |
| `get_skills`          | `(skill_type: SkillType)` | `read_supporting_document(SKILL_PATHS[skill_type])` |
| `get_resume`          | `()`                      | contents of `supporting_documents/json-resume.json` |
| `research_company`    | `()`                      | cached or freshly fetched company brief             |

- Do not expose a general file reader or a path argument.
- Do not add `list_histories` / `list_skill_types`; the enum members document valid values.
- Keep `read_supporting_document` as an internal helper.

## Company research (`job_applications/ai.py`)

Add `search_company(query)`, `fetch_pages(urls)`, `build_company_brief(company)`, and the
`research_company(ctx: RunContext[PipelineDeps]) -> str` tool to `ai.py`. The tool takes no arguments and
uses `ctx.deps.company`.

- Search: `client.search.query` with `$TINYFISH_API_KEY` and a query built from
  the company name (`"<company> company overview products engineering blog recent news"`).
- Fetch: `client.fetch.get_contents(urls=[...], format="markdown", purpose=...)` for the top 3–5
  result URLs.
- Return a markdown brief covering products, engineering, recent news, and culture signals, plus source
  URLs. Cap each page at ~2–3k characters and the total brief at ~8–10k characters.
- Cache: `collect_inputs` loads `application.company_research` into deps when
  `application.company_researched_at` is younger than 7 days and `force` is false. `research_company`
  returns the cached value if present; otherwise it calls TinyFish, stores the brief on deps, and the task
  persists it with `company_researched_at`.
- Fallbacks: missing `TINYFISH_API_KEY` returns `"Company research unavailable (no API key configured)."`;
  request errors return `"Company research unavailable: <reason>."`; partial fetch failures include the
  successful pages and note the failures. Research failures never fail the run.
- Delimit and truncate fetched text, and instruct the model in `tuning.md` to ignore instructions found
  inside tool output.

## PDF assembly (`Application.build_pdf`)

- Load `Application.tuning` and validate it against the vendored schema.
- Apply deterministic mutations:
  - set `$schema` to the canonical schema URL;
  - set `basics.email` to `benjc.vincent+{pk}@gmail.com`;
  - rewrite `basics.profiles[].url` for LinkedIn/GitHub/GitLab and the Google Coursera certificate URL to
    the `*.deuterium.dev` tracking URLs;
  - remove certificates based on `include_project_management` / `include_databricks`;
  - render `templates/payload.html` with `csl = tuning["payload"]` and the `breakout` value, then replace
    `resume["payload"]` with the rendered HTML.
- Remove the per-name `get_prompt(...)` lookups and the `SKILL_PROMPT_TO_NAME` / `job_histories` section
  mapping from `build_pdf`.
- Pass the document to `generate_pdf()`.
- If `self.tuning` is null or invalid, log a warning and render the base `json-resume.json` with the
  usual tracking/email/certificate mutations.

## Templates

- Add `application_manager/application_manager/templates/tuning.md` containing the instructions currently
  spread across `csl.md`, `job_name.md`, `skills_list.md`, `job_blurb.md`, and `resume_header.md`.
- Instruct the model to call `get_resume` first, return a full `ResumeDocument`, preserve every section
  and entry it is not tuning, tune only `basics.summary`, the four `work` summaries (Fortra, BVS,
  Staffbase, 10SPD), the four `skills` entries, and `payload`, and use only facts supported by the tools.
- Delete `csl.md`, `job_name.md`, `skills_list.md`, `job_blurb.md`, `job_analysis.md`, and
  `resume_header.md`.
- Keep `payload.html` and `breakout.md`.

## Tasks (`job_applications/tasks.py`)

- `generate_prompts` calls `ai.run_tuning(application_id, force=force)`.
- Catch one exception per run, store it on `application.prompt`, and retry as configured.
- Persist `company_research` and `company_researched_at` after a successful run.

## Admin (`job_applications/admin.py`)

- Add `provider` to `ApplicationAdmin`.
- Show `company_research` and `company_researched_at` read-only and add a "Refresh company research"
  action.
- Remove `name` and `provider` from `PromptAdmin.list_display` and fieldsets; remove `parent` and
  `children_list`; update `Prompt.__str__` to use the application instead of `name`.
- Change `prompts_list` on `ApplicationAdmin` to link `obj.prompt` instead of iterating `obj.prompts.all()`.
- Keep `regenerate_app_prompts` and `regenerate_prompts`.

## Configuration

- Add `TINYFISH_API_KEY` to `.env.example` and deployment config.
- Install the TinyFish Python SDK with `poetry add tinyfish` (adds `tinyfish>=0.2.3` to `pyproject.toml`).
  Use `from tinyfish import TinyFish` for `client.search.query(...)` and `client.fetch.get_contents(...)`.
- Add `jsonschema` with `poetry add jsonschema`.
- Vendor `json-resume-api/schema.json` at
  `application_manager/application_manager/supporting_documents/json-resume.schema.json`.
- Update the `PromptProvider` help text to remove tier-routing wording.

## Migrations

Run the `migrations` target in `application_manager/Makefile` after each change.

- Add `Application.provider` (nullable first, backfilled with the `gpt-4.1` provider or a placeholder,
  then altered to non-null `PROTECT`), `Application.tuning`, `Application.company_research`, and
  `Application.company_researched_at`.
- Remove `Prompt.provider`, `Prompt.parent`, and `Prompt.name`.
- Delete existing per-section `Prompt` rows in a data migration.
- Alter `Prompt.application` to a `OneToOneField` after the rows are deleted.

## Tests

- A valid full document passes the vendored schema; unknown root keys and malformed `iso8601` values are
  rejected.
- `merge_resume` preserves base sections and entries the model omitted.
- `ResumeDocument` round-trips through `model_dump(mode="json", by_alias=True)` and `model_validate`.
- `research_company` handles a request error, and a cached brief without network calls.
- `build_pdf` applies the tracking URLs, certificate toggles, and payload rendering to a valid tuning
  document, and falls back to the base resume when the blob is missing or invalid.
