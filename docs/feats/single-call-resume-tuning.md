# Single-call resume tuning with system-query tools

Status: planned, not started.
Context: replaces the staged pydantic-ai pipeline in `application_manager/job_applications/ai.py`.

## Goal

Move resume tuning from **11 LLM calls across 3 stages** to **one agent call**, and let the model
pull only the information it needs through tools that query the system (filesystem, `json-resume.json`,
the `Application` row) instead of preloading everything into `PipelineDeps`.

## What exists today

The pipeline (`job_applications/ai.py`) is already pydantic-ai based, but each output is its own call:

- Stage 0: `job_analysis` (cheap) -> structured `JobAnalysis`
- Stage 1: `csl`, `job_name`, 4x `skills_list`, 3x `job_blurb` (mostly cheap, blurbs strong)
- Stage 2: `header` (strong), consuming stage-1 blurbs

Each call is a `Prompt` row. `Application.build_pdf()` (`job_applications/models.py:132`) reads rows by
name:

- `csl`, `header`, `job_name`
- `frontend`, `backend`, `database`, `infrastructure`
- `bvs.md`, `staffbase.md`, `10SPD.md`

Tools exist (`get_job_description`, `get_skill_list`, `get_job_history`, `get_work_summaries`) but they are
not queries: `collect_inputs()` eagerly reads every history and skills file into `PipelineDeps` before the
run, and each tool just returns a dict entry.

The change is therefore two things:

1. Collapse 11 calls into one call with one structured output.
2. Replace the preloaded deps with real, lazy tools.

## Target shape

One `Agent` with `deps_type`, one structured `output_type`, and a toolset the model calls to fetch what it
needs. One `run_sync` per application. `ai.py` becomes:

`build agent -> run -> validate -> fan out results to storage`

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
  `template_vars` fields. Replace the `run_pipeline` loop with `run_tuning(deps, prompt, force)`.
- Reduce `collect_inputs` to application fields plus `application_id`; stop reading every document up
  front.
- Collapse the tier logic (`STRONG_MODEL` / `CHEAP_MODEL`) to a single model for the run (see tradeoffs).

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

### `job_applications/models.py`

- `Prompt.render()` / `format_response()` currently run template -> agent -> response. Either delete them
  (let `ai.py` own the call) or leave a thin `render_tuning`.
- Decide the storage shape (below). With fan-out, `build_pdf()` stays untouched.
- If caching is added, add an `input_hash` or run-marker field to `Prompt` (migration), or store a digest
  in `description`.

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

- `regenerate_app_prompts` / `regenerate_prompts` keep working.
- If per-section rows remain, `PromptAdmin` still shows them; mark the run row read-only and surface
  `error` prominently.
- If everything collapses to one row, the `children_list` / `parent` tree becomes noise.

### `services.py`

- No strict changes. `read_supporting_document` is already the right primitive; add
  `list_supporting_documents()` and an allowlist/sandbox check.

### `management/commands/generate_prompts.py`

- Effectively unchanged; it already dispatches the task.

### Config / dependencies

- `STRONG_MODEL` / `CHEAP_MODEL` collapse to a single model reference (or both survive only if analysis is
  split out again).
- Update `PromptProvider` help text (`models.py:263`), which documents tier routing.

### Migrations

- Only if a field/model is added for the run or cache hash. A fan-out design needs no migration.

## The storage decision (most important choice)

**Option A - fan-out (recommended).** One agent call, then map `TuningResult` onto the existing `Prompt`
rows (`csl`, `job_name`, `frontend`..., `bvs.md`..., `header`), joining lists back to comma strings and
keeping blurbs as plain text. `build_pdf()` stays untouched, sections remain editable in admin, and
rollback is easy. Add one `tuning` row (parent of the others) holding the rendered instruction, full JSON
response, and error.

**Option B - single blob.** Add a `JSONField` to `Application` (or a `PromptRun` model), store
`TuningResult` as JSON, and rewrite `build_pdf()` to read it. Cleaner artifact, much larger blast radius,
and per-section admin editing plus the existing prompt-name contract are lost.

Option A is the smaller, safer change. Option B is the cleaner model if editing individual sections does
not matter.

## Tradeoffs

- **Cost / latency.** Today: 9 cheap + 3 strong calls. A single call will likely need the strong model for
  the whole output. Fewer round trips may offset it; measure. If cost matters, split into two calls
  (analysis + generation), still far fewer than 11.
- **All-or-nothing.** One validation failure loses every section. Use pydantic-ai retries and only fan out
  after the result parses.
- **Prompt bloat.** The model must know which keys exist (`bvs.md`, `10SPD.md`, ...), so expose `list_*`
  tools and validate against enums/allowlists rather than free strings.
- **Caching.** `run_pipeline` currently skips a prompt when its rendered description is unchanged. With one
  call there is one cache key. Hash the application fields plus the content of every supporting document,
  because lazily fetched tool data never appears in the rendered template.
- **Admin semantics.** `Prompt.description` changes from a per-section instruction to the whole run
  instruction. Add a `role` / `kind` field if that distinction matters.

## Suggested sequencing

1. Add the output model and tool functions; prove one `run_sync` end-to-end against a sample application
   from the Django shell, still writing to the old `Prompt` names.
2. Swap `run_pipeline` for the single runner, keep fan-out, delete the stage machinery.
3. Delete the old templates and dead code; update admin/help text.
4. Add cache hashing and tests (tool allowlist, path traversal, fan-out mapping).

## Open questions

1. **Storage:** fan-out to existing `Prompt` rows (recommended) or one JSON blob?
2. **Tools:** live DB/FS queries, or keep preloaded deps and only consolidate the calls? Live queries are
   the point of the request but add the threading and path-safety work above.
3. **Model tier:** one strong model for the single call, or split analysis + generation to keep some cheap
   calls?
4. **Tool scope:** may the model read current `json-resume.json` sections (to reuse existing positions and
   dates), or only histories, skills, and notes?
