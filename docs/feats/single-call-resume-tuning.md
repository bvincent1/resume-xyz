# Single-call resume tuning with system-query tools

Status: planned, not started.
Context: replaces the staged pydantic-ai pipeline in `application_manager/job_applications/ai.py`.

## Goal

Move resume tuning from **11 LLM calls across 3 stages** to **one agent call**, and let the model
pull only the information it needs through tools that query the system (filesystem, `json-resume.json`,
the `Application` row) instead of preloading everything into `PipelineDeps`.

The result is stored as **one JSON blob** on the application rather than one row per resume section, and
the model provider moves from the individual prompt onto the application.

Tools expose **specific named resources**, never arbitrary filesystem paths, and identify resources with
**enum arguments** rather than free-form string keys. One additional tool performs **live company
background research through TinyFish** (web search + page fetch) so the tuning can be tailored to the
company without the model browsing arbitrary URLs.

## What exists today

The pipeline (`job_applications/ai.py`) is already pydantic-ai based, but each output is its own call:

- Stage 0: `job_analysis` (cheap) -> structured `JobAnalysis`
- Stage 1: `csl`, `job_name`, 4x `skills_list`, 3x `job_blurb` (mostly cheap, blurbs strong)
- Stage 2: `header` (strong), consuming stage-1 blurbs

Each call is a `Prompt` row, and each row carries its own `provider`. `Application.build_pdf()`
(`job_applications/models.py:132`) reads rows by name:

- `csl`, `header`, `job_name`
- `frontend`, `backend`, `database`, `infrastructure`
- `bvs.md`, `staffbase.md`, `10SPD.md`

Tools exist (`get_job_description`, `get_skill_list`, `get_job_history`, `get_work_summaries`) but they are
not queries: `collect_inputs()` eagerly reads every history and skills file into `PipelineDeps` before the
run, and each tool just returns a dict entry. Nothing currently looks outside the repo (no web research).

The change is therefore four things:

1. Collapse 11 calls into one call with one structured output.
2. Replace the preloaded deps with real, lazy tools over named resources.
3. Replace the per-section `Prompt` rows with one JSON blob, and move provider selection to the application.
4. Add a TinyFish-backed company research tool so the single call can ground its output in the company's
   public context.

## Target shape

One `Agent` with `deps_type`, one structured `output_type`, and a toolset the model calls to fetch what it
needs. One `run_sync` per application. `ai.py` becomes:

`build agent -> run (tools: local resources + TinyFish research) -> validate -> persist one JSON blob`

## File-by-file changes

### Resource enums and mappings (`job_applications/models.py`)

Define the resources the model may ask for as enums, and map them to files once:

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

The enum members mirror `job_histories` / `skills_types`; keep the enum values aligned with the `work`
names in `json-resume.json` so `build_pdf()` can match entries directly.

### `job_applications/ai.py` (main work)

- Replace `PROMPT_SPECS` with a single spec (`resume_tuning`), with
  `tools=("get_job_description", "get_notes", "get_history", "get_skills", "get_resume", "research_company")`.
- Replace `JobAnalysis` and the per-stage outputs with one output model, keyed by the enums:

```python
class TuningResult(BaseModel):
    header: str
    csl: list[str]
    job_names: dict[Company, str]      # one job title per company
    skills: dict[SkillType, list[str]] # one keyword list per skill type
    histories: dict[Company, str]      # one blurb per company
```

- Delete the stage machinery: `_parse_parent`, `build_context`, and the `stage` / `parent` /
  `template_vars` fields. Replace the `run_pipeline` loop with `run_tuning(application_id, force)`.
- Reduce `collect_inputs` to application fields plus `application_id` and `company`; stop reading every
  document up front. Also load the cached company research into deps (see below).
- Replace `prepare_prompts` with `prepare_run(application)`: upsert the single `resume_tuning` `Prompt`
  row (description, error reset) and read the model from **`application.provider`**, not from the prompt.
- `build_agent(application)` takes the provider from `application.provider`; the model cache stays keyed
  by provider.
- `run_tuning` returns a `TuningResult`; on success it writes:
  - `application.tuning = result.model_dump(mode="json")` (the parsed blob; JSON mode turns enum keys
    into their string values),
  - `prompt.response = result.model_dump_json()` (raw JSON, for audit/debug),
  - clears `prompt.error`,
  - persists any research gathered during the run (`company_research`, `company_researched_at`).
- On failure, set `prompt.error`; leave the previous `application.tuning` untouched.
- Collapse the tier logic (`STRONG_MODEL` / `CHEAP_MODEL`) to a single model for the run (see tradeoffs).

### New tool layer: local resources (in `ai.py` or a new `tools.py`)

Every tool returns one fixed resource. There is no generic file reader and no path argument.

| Tool | Signature | Returns |
| --- | --- | --- |
| `get_job_description` | `()` | `Application.description` |
| `get_notes` | `()` | `Application.notes` (interview questions) |
| `get_history` | `(company: Company)` | contents of `HISTORY_PATHS[company]` |
| `get_skills` | `(skill_type: SkillType)` | contents of `SKILL_PATHS[skill_type]` |
| `get_resume` | `()` | the full `supporting_documents/json-resume.json` |

```python
def get_history(ctx: RunContext[PipelineDeps], company: Company) -> str:
    """Return my work history for the given company."""
    return read_supporting_document(HISTORY_PATHS[company])

def get_skills(ctx: RunContext[PipelineDeps], skill_type: SkillType) -> str:
    """Return my skills for the given skill type."""
    return read_supporting_document(SKILL_PATHS[skill_type])
```

Implementation details:

- **No paths.** The tool schema exposes only the enum members, so the model cannot request an arbitrary
  file; the path-traversal surface disappears. `read_supporting_document` stays an internal helper used by
  the tools (and by `Application.build_pdf`), not a tool itself.
- **No list tools.** The enum argument documents the valid values in the tool schema, so
  `list_histories` / `list_skill_types` are unnecessary.
- **Threading.** pydantic-ai 2.59 executes sync tools via a thread executor (`run_in_executor` in
  `_utils.py`). Django DB connections are thread-local, so a sync tool hitting `Application.objects`
  opens a connection in that worker thread. Options:
  - keep `application_id` in deps and use `sync_to_async(thread_sensitive=True)`;
  - make the tools `async def`;
  - keep the local tools reading only files and add `django.db.close_old_connections()` around the run.

### New tool: `research_company` (TinyFish)

Add a `job_applications/research.py` module that owns the TinyFish calls, and register one agent tool:

```python
def research_company(ctx: RunContext[PipelineDeps]) -> str:
    """Research the company this application is for.

    Returns a short, source-backed brief (products, engineering, recent news,
    culture) plus source URLs. No arguments: the company comes from the
    application.
    """
```

The model calls it with **no arguments**; the company name comes from
`ctx.deps.company` (the `Application.company` field). There is no URL argument, so the model cannot
request arbitrary pages.

**API choice.** Use TinyFish's Search API plus Fetch API (both free within the daily allowance):

1. `GET https://api.search.tinyfish.ai` with `X-API-Key: $TINYFISH_API_KEY`, query built from the company
   name (e.g. `"<company> company overview products engineering blog recent news"`), plus the documented
   `purpose`/`location`/`language` params.
2. Take the top 3–5 result URLs and `POST https://api.fetch.tinyfish.ai` with
   `{"urls": [...], "format": "markdown", "purpose": "company background for resume tailoring"}`.
3. Return a compact markdown brief: company summary, product/engineering notes, recent news, culture
   signals, and a source list. Cap each fetched page (~2–3k chars) and the total payload (~8–10k chars)
   so the tool cannot blow the context budget.

The `tinyfish` Python SDK (`>=0.2.3`) wraps both calls (`client.search.query(...)`,
`client.fetch.get_contents(...)`); using it is optional — the existing `requests`/`httpx2` stack can hit
the REST endpoints directly. Pick one and keep it in `research.py`.

**Caching.** Company research changes slowly and is the slow/paid part of the run:

- Add `Application.company_research` (TextField/JSONField, null) and `Application.company_researched_at`
  (DateTimeField, null).
- Before the run, `collect_inputs` loads the cached brief into `deps.company_research` when it is younger
  than a TTL (e.g. 7 days) and `force` is false.
- `research_company` returns the cached value if present; otherwise it calls TinyFish, stores the brief on
  `deps`, and the task persists it after a successful run.
- This keeps DB writes out of the tool thread and gives one cache entry per application. Add a
  `research_company` admin action / `force` flag to refresh on demand.

**Failure handling.** The tool must never fail the resume run:

- Missing `TINYFISH_API_KEY` -> return `"Company research unavailable (no API key configured)."`
- Search/fetch error or timeout -> log and return `"Company research unavailable: <reason>."`
- Partial fetch failure -> include the successful pages and note the failures.
- Treat fetched page text as **untrusted data**: wrap it in a clear delimiter, truncate it, and instruct the
  model in `tuning.md` to ignore any instructions found inside tool output (prompt-injection defense).

**Prompting.** `tuning.md` asks the model to call `research_company` before writing the header and company
blurbs, use only facts supported by the brief or the job description, and avoid naming the company in the
blurbs themselves (matching current `job_blurb.md` behaviour).

### Storage model: one JSON blob on the application

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

Remove from `Prompt`:

- `provider` FK (moves to `Application`)
- `parent` FK and the `children` relation (no hierarchy in a single call)

Keep `Prompt` as a single run record per application:

- `name = "resume_tuning"`
- `description` = the rendered instruction
- `response` = the raw JSON blob
- `error` = failure text

`TuningResult` is the schema for `application.tuning`; validate with pydantic on write and on read.

### `job_applications/models.py` (`Application.build_pdf`)

Replace the per-name prompt lookups with one blob read, then apply it to `json-resume.json`:

```python
tuning = TuningResult.model_validate(self.tuning)
```

- `resume["payload"]` from `tuning.csl`
- `resume["basics"]["summary"]` from `tuning.header`
- work positions from `tuning.job_names` (iterate `Company` members or the mapping)
- work summaries from `tuning.histories`, matched to `work` entries by `Company` value
- skill keywords from `tuning.skills`, mapped through `SKILL_PROMPT_TO_NAME`

Keep the URL rewriting, email, certificate toggles, and `generate_pdf()` call unchanged. If
`self.tuning` is null or invalid, fall back to the untouched `json-resume.json` (log a warning) so
`build_pdf()` does not break on applications that have never been tuned.

### Templates (`application_manager/application_manager/templates/`)

- Add one `tuning.md` holding every instruction currently spread across `csl.md`, `job_name.md`,
  `skills_list.md`, `job_blurb.md`, `resume_header.md`, telling the model to call the named tools (including
  `research_company`) instead of expecting preloaded context.
- Delete the six now-unused templates; keep `payload.html` and `breakout.md`.

### `job_applications/tasks.py`

- `generate_prompts` keeps its signature but calls the single runner. Wrap the run in one try/except,
  since there is now one call. Persist `company_research` / `company_researched_at` after success.
  Add `close_old_connections()` if tools touch the ORM.
- Consider a shorter retry policy: one large call fails validation as a unit. Research failures are
  non-fatal, so they do not trigger a retry by themselves.

### `job_applications/admin.py`

- Move the provider field to `ApplicationAdmin` (Basic or Metadata tab).
- Show the cached `company_research` and `company_researched_at` (read-only) and add a
  "Refresh company research" action.
- `PromptAdmin`: remove `provider` from `list_display` and `fieldsets`; remove `parent` / `children_list`
  (no hierarchy).
- `prompts_list` still shows the single `resume_tuning` link.
- `regenerate_app_prompts` / `regenerate_prompts` keep working.

### `services.py` / `research.py`

- Keep `read_supporting_document` as the internal primitive for the fixed resource mappings. Do not
  expose a general filesystem reader.
- `research.py` owns the TinyFish client, query construction, fetch/truncation, and the fallback strings.

### `management/commands/generate_prompts.py`

- Effectively unchanged; it already dispatches the task. Optionally accept `--refresh-research`.

### Config / dependencies

- Add `TINYFISH_API_KEY` to the environment (`.env.example` and deployment config). Optional:
  `TINYFISH_TIMEOUT` and a research TTL setting.
- Add `tinyfish` to `pyproject.toml` if using the SDK; otherwise no new dependency.
- `STRONG_MODEL` / `CHEAP_MODEL` collapse to a single model reference, or disappear if the provider row
  is always chosen explicitly per application (or both survive only if analysis is split out again).
- Update `PromptProvider` help text (`models.py:263`), which currently documents tier routing.

### Migrations

- Add `Application.provider`, `Application.tuning`, `Application.company_research`,
  `Application.company_researched_at` (optional: `tuning_input_hash` for caching).
- Remove `Prompt.provider` and `Prompt.parent`.
- Existing per-section `Prompt` rows become unused. Either delete them in a data migration or leave them
  orphaned; there is no meaningful backfill into the blob.

## Tradeoffs

- **Cost / latency.** Today: 9 cheap + 3 strong calls. A single call will likely need the strong model for
  the whole output. Fewer round trips may offset it; measure. If cost matters, split into two calls
  (analysis + generation), still far fewer than 11.
- **Research adds a network dependency.** TinyFish Search/Fetch are free within the daily allowance, but
  they add latency and an external failure mode. Caching plus non-fatal fallbacks keep the pipeline usable
  when the API is down; the brief is stale for at most the TTL.
- **All-or-nothing.** One validation failure loses every section. Use pydantic-ai retries and only write
  `application.tuning` after the result parses.
- **Untrusted web content.** Fetched pages can contain prompt injection. Delimit and truncate the brief,
  keep it read-only inside the prompt, and rely on the model only for wording (not facts).
- **Lost per-section editing.** Sections are no longer individual admin rows; edits happen on the JSON
  blob (a JSON widget or a small form would help). The single `Prompt.response` keeps the raw output for
  reference.
- **Provider per application.** Each application can select its own model, which is useful for comparing
  providers, but means the provider must be set before a run (fall back to a configured default).
- **Enum serialization.** `dict[Company, ...]` is stored as string-keyed JSON; re-validating with
  `TuningResult.model_validate` coerces those keys back to enum members.
- **Tool surface.** Fixed resources mean adding a new company or skill type requires a new enum member and
  mapping entry, not a prompt change. The research tool takes no arguments, so the model cannot target
  arbitrary URLs.
- **Caching.** `run_pipeline` currently skips a prompt when its rendered description is unchanged. With one
  call there is one cache key. Hash the application fields plus the content of every supporting document,
  because lazily fetched tool data never appears in the rendered template. Company research has its own
  TTL-based cache.
- **Admin semantics.** `Prompt.description` is now the whole run instruction, and `Prompt.response` is the
  raw JSON blob rather than a single section.

## Suggested sequencing

1. Add `Company` / `SkillType` enums and the path mappings; add `Application.provider`,
   `Application.tuning`, and the research cache fields; move the provider admin field; remove
   `Prompt.provider` / `parent`.
2. Implement `research.py` (search + fetch + truncation + fallbacks) and prove it against a sample company
   from the Django shell with and without an API key.
3. Add the output model and the named resource tools (including `research_company`); prove one `run_sync`
   end-to-end against a sample application.
4. Rewrite `build_pdf()` to read `application.tuning`, with a fallback to the base resume.
5. Swap `run_pipeline` for the single runner, delete the stage machinery and old templates.
6. Add cache hashing (tuning and research) and tests (enum validation, blob validation, research fallback,
   `build_pdf` mapping).

## Open questions

1. **TinyFish surface:** Search + Fetch top pages (planned here, deterministic and free), or the
   Research API for a synthesized report (fewer moving parts in our code, but streaming/SSE and less
   control)?
2. **Research cache TTL:** 7 days by default, or refresh on every `force` run only?
3. **Research scope:** products/engineering/news only, or also culture/interview signals? The current
   `Application.notes` field already holds interview questions.
4. **Tools:** live DB/FS reads per call, or keep preloaded deps and only consolidate the calls? Live reads
   are the point of the request but add the threading work above.
5. **Model tier:** one strong model for the single call, or split analysis + generation to keep some cheap
   calls?
6. **Prompt row:** keep the single `resume_tuning` row as an audit record (planned here), or drop the
   `Prompt` model entirely now that provider and output live on `Application`?
