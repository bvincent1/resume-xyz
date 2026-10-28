# Single-call resume tuning with system-query tools

Status: planned, not started.
Context: replaces the staged pydantic-ai pipeline in `application_manager/job_applications/ai.py`.

## Goal

Move resume tuning from **11 LLM calls across 3 stages** to **one agent call**, and let the model
pull only the information it needs through tools that query the system (filesystem, `json-resume.json`,
the `Application` row) instead of preloading everything into `PipelineDeps`.

The result is stored as **one JSON blob** on the application rather than one row per resume section, and
the model provider moves from the individual prompt onto the application.

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
run, and each tool just returns a dict entry.

The change is therefore three things:

1. Collapse 11 calls into one call with one structured output.
2. Replace the preloaded deps with real, lazy tools.
3. Replace the per-section `Prompt` rows with one JSON blob, and move provider selection to the application.

## Target shape

One `Agent` with `deps_type`, one structured `output_type`, and a toolset the model calls to fetch what it
needs. One `run_sync` per application. `ai.py` becomes:

`build agent -> run -> validate -> persist one JSON blob`

## File-by-file changes

### `job_applications/ai.py` (main work)

- Replace `PROMPT_SPECS` with a single spec (`resume_tuning`).
- Replace `JobAnalysis` and the per-stage outputs with one output model:

```python
class WorkBlurb(BaseModel):
    key: str          # e.g. "bvs.md"
    summary: str

class TuningResult(BaseModel):
    header: str
    csl: list[str]
    job_names: list[str]            # one per history, in job_histories order
    skills: dict[str, list[str]]    # frontend/backend/database/infrastructure
    histories: list[WorkBlurb]
```

- Delete the stage machinery: `_parse_parent`, `build_context`, and the `stage` / `parent` /
  `template_vars` fields. Replace the `run_pipeline` loop with `run_tuning(application_id, force)`.
- Reduce `collect_inputs` to application fields plus `application_id`; stop reading every document up
  front.
- Replace `prepare_prompts` with `prepare_run(application)`: upsert the single `resume_tuning` `Prompt`
  row (description, error reset) and read the model from **`application.provider`**, not from the prompt.
- `build_agent(application)` takes the provider from `application.provider`; the model cache stays keyed
  by provider.
- `run_tuning` returns a `TuningResult`; on success it writes:
  - `application.tuning = result.model_dump()` (the parsed blob),
  - `prompt.response = result.model_dump_json()` (raw JSON, for audit/debug),
  - clears `prompt.error`.
- On failure, set `prompt.error`; leave the previous `application.tuning` untouched.
- Collapse the tier logic (`STRONG_MODEL` / `CHEAP_MODEL`) to a single model for the run (see tradeoffs).

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
- work positions from `zip(job_histories, tuning.job_names)`
- work summaries from `{b.name: b.summary for b in tuning.histories}`
- skill keywords from `tuning.skills`, mapped through `SKILL_PROMPT_TO_NAME`

Keep the URL rewriting, email, certificate toggles, and `generate_pdf()` call unchanged. If
`self.tuning` is null or invalid, fall back to the untouched `json-resume.json` (log a warning) so
`build_pdf()` does not break on applications that have never been tuned.

### New tool layer (in `ai.py` or a new `tools.py`)

| Tool | Reads | Notes |
| --- | --- | --- |
| `get_job_description()` | `Application.description` | no args |
| `get_notes()` | `Application.notes` | interview questions; currently unused by prompts |
| `list_histories()` | `job_histories` / docs dir | lets the model discover valid keys instead of guessing |
| `get_history(company_key)` | `supporting_documents/histories/*.md` | validate against allowlist |
| `list_skill_types()` | `skills_types` | |
| `get_skills(skill_type)` | `supporting_documents/*_skills.md` | validate against allowlist |
| `get_resume_section(section)` | `json-resume.json` | optional: lets the model see current positions/dates |
| `read_supporting_document(path)` | filesystem | only if free-form access is wanted; must be sandboxed |

Implementation details:

- **Path safety.** A general file reader must resolve the path and assert it stays under
  `supporting_documents/`; otherwise the model can request `../../.env`.
- **Threading.** pydantic-ai 2.59 executes sync tools via a thread executor (`run_in_executor` in
  `_utils.py`). Django DB connections are thread-local, so a sync tool hitting `Application.objects`
  opens a connection in that worker thread. Options:
  - keep `application_id` in deps and use `sync_to_async(thread_sensitive=True)`;
  - make the tools `async def`;
  - keep tools filesystem-only and add `django.db.close_old_connections()` around the run.

### Templates (`application_manager/application_manager/templates/`)

- Add one `tuning.md` holding every instruction currently spread across `csl.md`, `job_name.md`,
  `skills_list.md`, `job_blurb.md`, `resume_header.md`, telling the model to call tools instead of
  expecting preloaded context.
- Delete the six now-unused templates; keep `payload.html` and `breakout.md`.

### `job_applications/tasks.py`

- `generate_prompts` keeps its signature but calls the single runner. Wrap the run in one try/except,
  since there is now one call. Add `close_old_connections()` if tools touch the ORM.
- Consider a shorter retry policy: one large call fails validation as a unit.

### `job_applications/admin.py`

- Move the provider field to `ApplicationAdmin` (Basic or Metadata tab).
- `PromptAdmin`: remove `provider` from `list_display` and `fieldsets`; remove `parent` / `children_list`
  (no hierarchy).
- `prompts_list` still shows the single `resume_tuning` link.
- `regenerate_app_prompts` / `regenerate_prompts` keep working.

### `services.py`

- No strict changes. `read_supporting_document` is already the right primitive; add
  `list_supporting_documents()` and an allowlist/sandbox check.

### `management/commands/generate_prompts.py`

- Effectively unchanged; it already dispatches the task.

### Config / dependencies

- `STRONG_MODEL` / `CHEAP_MODEL` collapse to a single model reference, or disappear if the provider row
  is always chosen explicitly per application (or both survive only if analysis is split out again).
- Update `PromptProvider` help text (`models.py:263`), which currently documents tier routing.

### Migrations

- Add `Application.provider` and `Application.tuning` (optional: `tuning_input_hash` for caching).
- Remove `Prompt.provider` and `Prompt.parent`.
- Existing per-section `Prompt` rows become unused. Either delete them in a data migration or leave them
  orphaned; there is no meaningful backfill into the blob.

## Tradeoffs

- **Cost / latency.** Today: 9 cheap + 3 strong calls. A single call will likely need the strong model for
  the whole output. Fewer round trips may offset it; measure. If cost matters, split into two calls
  (analysis + generation), still far fewer than 11.
- **All-or-nothing.** One validation failure loses every section. Use pydantic-ai retries and only write
  `application.tuning` after the result parses.
- **Lost per-section editing.** Sections are no longer individual admin rows; edits happen on the JSON
  blob (a JSON widget or a small form would help). The single `Prompt.response` keeps the raw output for
  reference.
- **Provider per application.** Each application can select its own model, which is useful for comparing
  providers, but means the provider must be set before a run (fall back to a configured default).
- **Prompt bloat.** The model must know which keys exist (`bvs.md`, `10SPD.md`, ...), so expose `list_*`
  tools and validate against enums/allowlists rather than free strings.
- **Caching.** `run_pipeline` currently skips a prompt when its rendered description is unchanged. With one
  call there is one cache key. Hash the application fields plus the content of every supporting document,
  because lazily fetched tool data never appears in the rendered template.
- **Admin semantics.** `Prompt.description` is now the whole run instruction, and `Prompt.response` is the
  raw JSON blob rather than a single section.

## Suggested sequencing

1. Add `Application.provider` and `Application.tuning`; move the provider admin field; remove
   `Prompt.provider` / `parent`.
2. Add the output model and tool functions; prove one `run_sync` end-to-end against a sample application
   from the Django shell.
3. Rewrite `build_pdf()` to read `application.tuning`, with a fallback to the base resume.
4. Swap `run_pipeline` for the single runner, delete the stage machinery and old templates.
5. Add cache hashing and tests (tool allowlist, path traversal, blob validation, `build_pdf` mapping).

## Open questions

1. **Tools:** live DB/FS queries, or keep preloaded deps and only consolidate the calls? Live queries are
   the point of the request but add the threading and path-safety work above.
2. **Model tier:** one strong model for the single call, or split analysis + generation to keep some cheap
   calls?
3. **Tool scope:** may the model read current `json-resume.json` sections (to reuse existing positions and
   dates), or only histories, skills, and notes?
4. **Prompt row:** keep the single `resume_tuning` row as an audit record (planned here), or drop the
   `Prompt` model entirely now that provider and output live on `Application`?
