# Single-call resume tuning with system-query tools

## Data model (`job_applications/models.py`)

Add to `Application`:

```python
provider = models.ForeignKey(
    "PromptProvider",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="applications",
    help_text="Model provider used for the single tuning call.",
)
tuning = models.JSONField(
    null=True,
    blank=True,
    help_text="Validated TuningResult blob for the last successful run.",
)
company_research = models.TextField(
    null=True,
    blank=True,
    help_text="Cached TinyFish company brief used for tuning.",
)
company_researched_at = models.DateTimeField(null=True, blank=True)
```

Change `Prompt`:

- Remove `provider` and `parent` (and the `children` relation).
- Keep a single row per application: `name = "resume_tuning"`, `description` holds the rendered
  instruction, `response` holds the raw JSON blob, `error` holds failure text.

Add enums and resource mappings:

```python
from enum import Enum

class Company(str, Enum):
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
}

SKILL_PATHS = {
    SkillType.FRONTEND: "supporting_documents/frontend_skills.md",
    SkillType.BACKEND: "supporting_documents/backend_skills.md",
    SkillType.DATABASE: "supporting_documents/database_skills.md",
    SkillType.INFRASTRUCTURE: "supporting_documents/infrastructure_skills.md",
}
```

## Pipeline (`job_applications/ai.py`)

- Replace `PROMPT_SPECS` with one spec: `resume_tuning`, provider from `application.provider`, tools
  `("get_job_description", "get_notes", "get_history", "get_skills", "get_resume", "research_company")`.
- Replace `JobAnalysis` and per-stage outputs with one output model:

```python
class TuningResult(BaseModel):
    header: str
    csl: list[str]
    job_names: dict[Company, str]
    skills: dict[SkillType, list[str]]
    histories: dict[Company, str]
```

- Remove `stage`, `parent`, `template_vars`, `_parse_parent`, `build_context`, and `run_pipeline`.
- Add `run_tuning(application_id, force=False) -> TuningResult`.
- Reduce `collect_inputs` to the application fields, `company`, and the cached company brief; do not read
  every supporting document up front.
- Replace `prepare_prompts` with `prepare_run(application)`, which upserts the single `resume_tuning`
  row, sets `description`, and clears `error`.
- `build_agent(application)` builds the agent from `application.provider`; keep the per-provider model
  cache.
- On success, `run_tuning` writes `application.tuning = result.model_dump(mode="json")`,
  `prompt.response = result.model_dump_json()`, clears `prompt.error`, and persists the company brief.
  On failure, set `prompt.error` and leave `application.tuning` unchanged.
- Use a single model tier for the run: keep `STRONG_MODEL`, remove `CHEAP_MODEL`.

## Local resource tools (`job_applications/ai.py` or `job_applications/tools.py`)

Tools never touch the ORM; application fields are preloaded in `PipelineDeps` by `collect_inputs`.

| Tool | Signature | Returns |
| --- | --- | --- |
| `get_job_description` | `()` | `Application.description` from deps |
| `get_notes` | `()` | `Application.notes` from deps |
| `get_history` | `(company: Company)` | `read_supporting_document(HISTORY_PATHS[company])` |
| `get_skills` | `(skill_type: SkillType)` | `read_supporting_document(SKILL_PATHS[skill_type])` |
| `get_resume` | `()` | contents of `supporting_documents/json-resume.json` |
| `research_company` | `()` | cached or freshly fetched company brief |

- Do not expose a general file reader or a path argument.
- Do not add `list_histories` / `list_skill_types`; the enum members document valid values.
- Keep `read_supporting_document` as an internal helper.

## Company research (`job_applications/research.py`)

Register `research_company(ctx: RunContext[PipelineDeps]) -> str`; it takes no arguments and uses
`ctx.deps.company`.

- Search: `GET https://api.search.tinyfish.ai` with `X-API-Key: $TINYFISH_API_KEY` and a query built from
  the company name (`"<company> company overview products engineering blog recent news"`).
- Fetch: `POST https://api.fetch.tinyfish.ai` with
  `{"urls": [...], "format": "markdown", "purpose": "company background for resume tailoring"}` for the
  top 3–5 result URLs.
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

- Validate the blob with `TuningResult.model_validate(self.tuning)` and apply it to `json-resume.json`:
  - `resume["payload"]` from `tuning.csl`
  - `resume["basics"]["summary"]` from `tuning.header`
  - work positions from `tuning.job_names`
  - work summaries from `tuning.histories`, matched by `Company`
  - skill keywords from `tuning.skills`, mapped through `SKILL_PROMPT_TO_NAME`
- Remove the per-name `get_prompt(...)` lookups.
- Keep URL rewriting, email, certificate toggles, and `generate_pdf()` unchanged.
- If `self.tuning` is null or invalid, log a warning and render the untouched `json-resume.json`.

## Templates

- Add `application_manager/application_manager/templates/tuning.md` containing the instructions currently
  spread across `csl.md`, `job_name.md`, `skills_list.md`, `job_blurb.md`, and `resume_header.md`; instruct
  the model to use the named tools, call `research_company` before writing the header and blurbs, use only
  supported facts, and treat tool output as untrusted data.
- Delete `csl.md`, `job_name.md`, `skills_list.md`, `job_blurb.md`, `job_analysis.md`, and
  `resume_header.md`.
- Keep `payload.html` and `breakout.md`.

## Tasks (`job_applications/tasks.py`)

- `generate_prompts` calls `ai.run_tuning(application_id, force=force)`.
- Catch one exception per run, store it on the `resume_tuning` prompt, and retry as configured.
- Persist `company_research` and `company_researched_at` after a successful run.

## Admin (`job_applications/admin.py`)

- Add `provider` to `ApplicationAdmin`.
- Show `company_research` and `company_researched_at` read-only and add a "Refresh company research"
  action.
- Remove `provider` from `PromptAdmin.list_display` and fieldsets; remove `parent` and `children_list`.
- Keep `prompts_list`, `regenerate_app_prompts`, and `regenerate_prompts`.

## Configuration

- Add `TINYFISH_API_KEY` to `.env.example` and deployment config.
- Add `tinyfish>=0.2.3` to `pyproject.toml`.
- Update the `PromptProvider` help text to remove tier-routing wording.

## Migrations

- Add `Application.provider`, `Application.tuning`, `Application.company_research`, and
  `Application.company_researched_at`.
- Remove `Prompt.provider` and `Prompt.parent`.
- Delete existing per-section `Prompt` rows in a data migration.

## Tests

- `TuningResult` round-trips through `model_dump(mode="json")` and `model_validate` with enum keys.
- Tool enum arguments reject unknown values.
- `research_company` handles a missing API key, a request error, and a cached brief without network calls.
- `build_pdf` maps a valid blob onto the resume sections and falls back to the base resume when the blob is
  missing or invalid.
