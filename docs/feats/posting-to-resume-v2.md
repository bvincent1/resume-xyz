# Posting -> Resume pipeline (v2)

Status: planned, not started.
Source brief: `docs/feats/posting-to-resume-breakdown.md`

## Goal

Create a pipeline that combines job application information and AI to optimize resume data.

## Decisions taken (with user)

| Topic | Decision |
| --- | --- |
| Provider config | Pull provider details from the `PromptProvider` model in `job_applications/models.py`. Models are added ad hoc in the admin; code only looks one up by its `name`. |
| Prompt text source | Keep the Jinja templates in `application_manager/templates/`. |
| Trigger | Auto-dispatch on Application create/update. |
| AI output scope | Keep the snippet model: AI fills the existing `Prompt` rows, `build_pdf()` is unchanged. |

Note on the brief's "no dynamic or external configs, just functions inside task(s)" criterion: this is satisfied
in the sense that no *new* config surface is introduced. Prompt-to-model routing, provider resolution and
prompt rendering are plain functions in `job_applications/ai.py`. The single DB-driven lookup is provider
credentials/endpoints, per the decision above.

## Current state (as of `379637fd`)

- `Application.save()` -> `generate_all_prompts()` renders Jinja templates into `Prompt` rows with an empty
  `response`; a human pastes the answer into the admin. Nothing calls an LLM today.
- `Application.build_pdf()` splices `Prompt.response` values into `supporting_documents/json-resume.json`
  and POSTs it to `json-resume-api`.
- `Prompt.parent` (self FK) already exists and is unused — it is the hook for parent/child prompt data.
- `PromptProvider` (name, url, headers) exists but is unused; `Prompt.provider` is commented out.
- `templates/*.md`: `job_blurb.md`, `csl.md`, `job_name.md`, `skills_list.md`, `resume_header.md`, `breakout.md`,
  `payload.html`.
- Bug: the management command file is `rengen_prompts.py` but `application_manager/Makefile` calls
  `regen_prompts`, so `make prompts` is broken.

## Target architecture

```
Application.save()  --(transaction.on_commit)-->  celery task `generate_prompts`
                                                            |
                                    collect_inputs()  [sync: DB + file reads]
                                                            |
                                      asyncio.run(run_pipeline())  [async: LLM only]
                                        1. parent: job_analysis  (cheap model, structured output)
                                        2. children, concurrent (blurbs use strong model)
                                        3. header consumes sibling blurbs (strong model)
                                                            |
                                    persist_results()  [sync: DB writes]
```

### Provider resolution

```python
def resolve_model(name: str) -> Model:
    """Look up a PromptProvider row by name and build a pydantic-ai Model.

    Every provider is an OpenAI-compatible endpoint:
      url     -> base_url
      headers -> HTTP headers (including `Authorization: Bearer <key>`)
      name    -> the model id sent to the API, and the lookup key
    """
```

- `PromptProvider.headers["Authorization"]` supplies the `api_key` for `OpenAIProvider`; remaining headers go
  on an `httpx.AsyncClient`.
- Missing row -> raise `ProviderNotConfigured(name)` listing the configured names, so "added ad hoc" is a
  clear error rather than a stack trace.
- Assumption: OpenAI-compatible wire format only. `name` doubles as the model id (e.g.
  `openai/gpt-4.1-mini` for OpenRouter). A native Anthropic endpoint would need a second code path, which
  conflicts with the "no alternate paths" rule.

### Prompt -> model tier routing (code, not config)

```python
STRONG_MODEL = "gpt-4.1"       # PromptProvider.name
CHEAP_MODEL  = "gpt-4.1-mini"  # PromptProvider.name

PROMPT_TIERS = {          # satisfies "delegate simple prompts to cheaper providers"
    "job_analysis": CHEAP,   # structured extraction
    "csl": CHEAP,            # keyword list
    "job_name": CHEAP,       # title
    "frontend": CHEAP, "backend": CHEAP, "database": CHEAP, "infrastructure": CHEAP,
    "bvs.md": STRONG, "staffbase.md": STRONG, "10SPD.md": STRONG,  # prose
    "header": STRONG,        # prose synthesis
}
```

### Parent -> child data flow

New parent prompt `job_analysis` (new template `templates/job_analysis.md`), `output_type=JobAnalysis`:

```python
class JobAnalysis(BaseModel):
    title: str
    seniority: str
    responsibilities: list[str]
    required_skills: list[str]
    keywords: list[str]
```

- The parent `Prompt` row (`name="job_analysis"`, `response` = JSON dump) is the `parent` of every child row.
- Children receive the parent's typed object as agent `deps` **and** as Jinja context, so the stored
  `Prompt.description` shows the parent data that fed it.
- Two-stage run: the three blurbs run concurrently; `header` then consumes the blurbs through the
  `get_work_summaries()` tool. The remaining children run concurrently with the blurbs.

### Tool design (no DB access inside the coroutine)

All supporting documents and provider rows are read *synchronously* before `asyncio.run`, then passed into
the coroutine as `deps`:

```python
@dataclass
class PipelineDeps:
    job_description: str
    histories: dict[str, str]      # {"bvs.md": "<markdown>", ...}
    skills: dict[str, str]         # {"frontend": "<markdown>", ...}
    company: str
```

Tools read from `deps`, never from the DB:

- `@agent.tool get_job_description()` -> parent agent
- `@agent.tool get_skill_list(skill_type)` -> skills agents
- `@agent.tool get_job_history(company_key)` -> blurb agents
- `@agent.tool get_work_summaries()` -> header agent (sibling blurbs = parent -> child flow)

### Async task

```python
@shared_task
def generate_prompts(application_id: int, force: bool = False):
    inputs = collect_inputs(application_id)      # sync reads (DB + files)
    results = asyncio.run(run_pipeline(inputs))  # async: LLM calls only
    persist_results(application_id, results)      # sync writes
```

- Celery tasks are sync -> `asyncio.run` inside the task; the `httpx` client is created *inside* the coroutine
  (event-loop affinity).
- Django ORM is never touched inside the coroutine (avoids `SynchronousOnlyOperation`).
- Concurrency bounded by an `asyncio.Semaphore` (default 4) so one application does not fan out 9 calls.
- Per-prompt failure -> that prompt's `response` stays empty and `Prompt.error` is set; the rest still persist.

### Output contract (snippet model preserved)

- `Prompt.response` keeps its current shape: prose for blurbs/header/job_name, comma-separated for
  `csl`/skills -> `build_pdf()` is unchanged.
- Structure is still enforced at generation time by `output_type=list[str]`, then joined for storage.
- No CSV parsing of free-form text, no JSON-in-textfield migration.

### Auto-dispatch on save

- `Application.save()` -> `transaction.on_commit(lambda: generate_prompts.delay(pk))`.
- Dispatch only when `description`, `title`, or `company` actually changed (compare against the stored row);
  otherwise every admin save of `notes`/`status` burns tokens. Creation always dispatches.
- `build_pdf()`'s `self.save()` triggers nothing, because it does not change those fields.
- Broker down -> catch the connection error, log a warning, do not break the admin save.
- The admin action "Regenerate prompts" calls the task with `force=True`.

## Work items

1. **Dependency** — `pyproject.toml`: add
   `pydantic-ai-slim = { extras = ["openai"], version = "^2.59" }` (pydantic-ai 2.59.0 current; `httpx` comes
   with the `openai` extra). Keep the existing `openai` dep.

2. **`job_applications/ai.py` (new)** — `JobAnalysis` model, `PipelineDeps`, `resolve_model`, provider-not-configured
   error, agent builders, tool registrations, prompt tier table, `collect_inputs`, `run_pipeline`,
   `persist_results`.

3. **`job_applications/tasks.py`** — add the `generate_prompts` celery task (sync wrapper + `asyncio.run`).

4. **`job_applications/models.py`** —
   - delete `generate_job_histories_prompts`, `generate_payload_prompt`, `generate_header_prompt`,
     `generate_skills_prompts`, `generate_job_name_prompt`, `generate_all_prompts`;
   - `save()` -> dispatch task on commit when description/title/company changed;
   - add `Prompt.error = models.TextField(null=True, blank=True)`;
   - drop the unused `PromptProvider.get_default_pk()` and the commented-out `Prompt.provider` FK block.

5. **`job_applications/admin.py`** — "Regenerate prompts" action dispatches the task with `force=True`;
   show `Prompt.error`; add `PromptProvider` help text describing url/headers/name semantics.

6. **Templates** — new `templates/job_analysis.md`; extend `job_blurb.md`, `csl.md`, `job_name.md`,
   `skills_list.md`, `resume_header.md` with parent-context vars.

7. **Management command** — replace `rengen_prompts.py` with `generate_prompts.py` (dispatch the task);
   update the `prompts:` target in `application_manager/Makefile` to `generate_prompts`.

8. **Migration** — `Prompt.error`.

9. **Tests** — `job_applications/tests.py` (currently an empty stub): pipeline test with pydantic-ai's
   `FunctionModel`/`TestModel` — asserts the parent runs first, children receive the parent data,
   `Prompt.parent` is set, and cheap/strong routing picks the right provider row. No network, no API key.

## Acceptance criteria mapping

| Criterion | How |
| --- | --- |
| pydantic_ai for prompting + tool management | `Agent` per prompt type with `output_type`, `@agent.tool` for `get_job_description` / `get_skill_list` / `get_job_history` / `get_work_summaries` |
| no dynamic or external configs, just functions inside task(s) | routing table + provider resolution + prompt rendering are plain functions in `job_applications/ai.py`; the only DB-driven piece is provider credentials/endpoints, per the decision above |
| delegate simple / basic prompts to cheaper providers | `PROMPT_TIERS` sends extraction/list prompts to `CHEAP_MODEL`, prose to `STRONG_MODEL` |

## Risks / open items

1. **OpenAI-compatible wire format assumption** for all `PromptProvider` rows — a native Anthropic endpoint will
   not work. Would need a `kind` column if that changes.
2. **Cost per application** ~ 1 cheap parent + 4 cheap children + 3 strong blurbs + 1 strong header = ~9 calls.
   Auto-dispatch on every description edit multiplies that.
3. `Prompt.description` now embeds parent data, so it gets long in the admin view.
4. The task upserts `Prompt` rows by name, matching today's `get_prompt` behaviour.
5. Existing `Prompt.response` rows keep their current format; no data migration needed.
