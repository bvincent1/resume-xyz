# Posting -> Resume pipeline (v2) — example implementation

Status: planned, not started.
Source brief: `docs/feats/posting-to-resume-breakdown.md`

Implements: the plumbing plus **2 of 11 prompts** (`job_analysis` parent + `csl` child) as a worked example.
The remaining 9 prompts are left to you — see [Adding the remaining prompts](#adding-the-remaining-prompts-your-part).

## Scope of this plan

| Built here | Left to you |
| --- | --- |
| `pydantic-ai` dependency, provider resolution, model tiers | the `job_name` prompt |
| the async celery task, semaphore, error capture | the 4 skills prompts (`frontend`, `backend`, `database`, `infrastructure`) |
| `PipelineDeps` + the tool pattern | the 3 company blurbs (`bvs.md`, `staffbase.md`, `10SPD.md`) |
| prompt rendering on the `Prompt` model (`Prompt.render`) | the `header` prompt |
| parent/child wiring via `Prompt.parent` | — |
| auto-dispatch on `Application.save()`, admin action, management command | — |
| `job_analysis` (parent) and `csl` (one child) | — |
| tests with a stubbed model | — |

Why two prompts and not one: `job_analysis`'s only purpose is to feed children. A parent with no child
produces no change to the resume and leaves the typed-data handoff unproven. `csl` is the cheapest child
that exercises the whole path (parent data -> child agent -> `Prompt.response` -> `build_pdf()` input).

## Decisions taken (with user)

| Topic | Decision |
| --- | --- |
| Provider config | Pull provider details from the `PromptProvider` model in `job_applications/models.py`. Models are added ad hoc in the admin; code only looks one up by its `name`. |
| Prompt text source | Keep the Jinja templates in `application_manager/templates/`. |
| Prompt rendering | Lives on the `Prompt` model (`Prompt.render`), not in a standalone function. |
| Trigger | Auto-dispatch on Application create/update. |
| AI output scope | Keep the snippet model: AI fills the existing `Prompt` rows, `build_pdf()` is unchanged. |

Note on the brief's "no dynamic or external configs, just functions inside task(s)" criterion: this is satisfied
in the sense that no *new* config surface is introduced. Prompt-to-model routing, provider resolution and
prompt rendering are code. The single DB-driven lookup is provider credentials/endpoints, per the decision above.

## Current state (as of `379637fd`)

- `Application.save()` -> `generate_all_prompts()` renders Jinja templates into `Prompt` rows with an empty
  `response`; a human pastes the answer into the admin. Nothing calls an LLM today.
- Rendering happens in `Application.generate_*_prompts()` via the module-level Jinja `env` in `models.py`
  (that `env` moves to `services.py` in this plan).
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
        collect_inputs() + prepare_prompts()   [sync: DB + file reads, Prompt rows upserted]
                                                            |
                                      asyncio.run(run_pipeline())  [async: LLM only]
                                        stage 0: job_analysis  (cheap model, structured output)
                                        stage 1: csl           (cheap model, list output, consumes parent)
                                                            |
                                    persist_results()  [sync: DB writes]
```

### Prompt rendering lives on the Prompt model

The Jinja machinery moves into `job_applications/services.py`, next to the other rendering service
(`render_pdf`), so there is one place that knows how templates are loaded:

```python
# job_applications/services.py
from django.conf import settings
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader(str(settings.BASE_DIR / "application_manager")))


def render_template(template_name, **context) -> str:
    """Render a Jinja template from the project directory with the given context."""
    return env.get_template(template_name).render(**context)
```

`Prompt` owns the call, so the pipeline never calls a free function to build a prompt:

```python
# job_applications/models.py
from .services import FileService, render_pdf, render_template


class Prompt(models.Model):
    template = models.CharField(blank=True, default="")
    description = models.TextField(blank=False, null=False)
    ...

    def render(self, **context) -> str:
        """Render this prompt's template into `description` and return it."""
        self.description = render_template(self.template, **context)
        return self.description
```

- `models.py` drops its own `env` and the `jinja2` import; `build_pdf()` switches to
  `render_template("templates/breakout.md", url=..., base_64_url=...)` and
  `render_template("templates/payload.html", csl=..., breakout=...)`.
- Templates stay addressed relative to the project directory (`templates/csl.md`), so the loader path is
  unchanged from today.
- `template` is a new column: each row records which template produced it, so the admin shows the source
  alongside the rendered text.
- The pipeline upserts the `Prompt` rows first (template + `parent` FK), then calls `prompt.render(**context)`
  on the in-memory instance during the run, and saves `description` + `response` together at the end. One
  render per prompt, no duplication between "text sent to the model" and "text stored for review".

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
```

Routing is per prompt spec (see `PromptSpec.tier` below), so extraction/list prompts go to `CHEAP_MODEL`
and prose prompts go to `STRONG_MODEL`. The example implements two cheap prompts; the strong tier is wired
but only exercised once you add a prose prompt.

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
- Stages: stage 0 is the parent; stage 1 depends only on the parent; stage 2 depends on stage-1 siblings
  (the `header` prompt consumes the blurbs). The example implements stage 0 and one stage-1 child.

### Tool design (no DB access inside the coroutine)

All supporting documents and provider rows are read *synchronously* before `asyncio.run`, then passed into
the coroutine as `deps`:

```python
@dataclass
class PipelineDeps:
    """Everything the agents may read.

    Collected synchronously before the event loop starts, so no tool ever
    touches the DB or the filesystem. `work_summaries` is filled in between
    stages for prompts that consume sibling output.
    """
    job_description: str
    company: str
    histories: dict[str, str] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    work_summaries: dict[str, str] = field(default_factory=dict)
```

Tools read from `deps`, never from the DB:

- `@agent.tool get_job_description()` -> parent agent (implemented in the example)
- `@agent.tool get_skill_list(skill_type)` -> skills agents (yours)
- `@agent.tool get_job_history(company_key)` -> blurb agents (yours)
- `@agent.tool get_work_summaries()` -> header agent, reads `deps.work_summaries` (yours)

### Async task

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def generate_prompts(self, application_id: int, force: bool = False):
    deps = collect_inputs(application_id)          # sync reads (DB + files)
    prompts = prepare_prompts(application_id)      # sync: upsert Prompt rows (template, parent)
    results = asyncio.run(run_pipeline(deps, prompts))  # async: LLM calls only
    persist_results(prompts, results)              # sync writes
```

- Celery tasks are sync -> `asyncio.run` inside the task; the `httpx` client is created *inside* the coroutine
  (event-loop affinity).
- Django ORM is never touched inside the coroutine (avoids `SynchronousOnlyOperation`). In-memory model
  mutation is fine, which is how `Prompt.render()` is used during the run.
- Concurrency bounded by an `asyncio.Semaphore` (default 4).
- Per-prompt failure -> that prompt's `response` stays empty and `Prompt.error` is set; the rest still persist.
  Use `asyncio.gather(..., return_exceptions=True)` so one failure does not sink the stage.

### Output contract (snippet model preserved)

- `Prompt.response` keeps its current shape: prose for blurbs/header/job_name, comma-separated for
  `csl`/skills -> `build_pdf()` is unchanged.
- Structure is still enforced at generation time by `output_type=list[str]`, then joined for storage.
- No CSV parsing of free-form text, no JSON-in-textfield migration.
- The parent's `response` is the JSON dump of `JobAnalysis` (`model_dump_json()`).

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

2. **`job_applications/services.py`** — add the Jinja environment and the `render_template(template_name,
   **context)` helper (moved out of `models.py`), alongside `render_pdf` and `FileService`.

3. **`job_applications/models.py`** —
   - add `Prompt.template = models.CharField(blank=True, default="")` and
     `Prompt.error = models.TextField(null=True, blank=True)`;
   - add `Prompt.render(**context)` — delegates to `render_template()` from `.services`;
   - delete the module-level `env` and the `jinja2` import; switch `build_pdf()` to `render_template()`;
   - delete `generate_job_histories_prompts`, `generate_payload_prompt`, `generate_header_prompt`,
     `generate_skills_prompts`, `generate_job_name_prompt`, `generate_all_prompts`;
   - `save()` -> dispatch the task on commit when description/title/company changed;
   - drop the unused `PromptProvider.get_default_pk()` and the commented-out `Prompt.provider` FK block.

4. **`job_applications/ai.py` (new)** — `JobAnalysis`, `PipelineDeps`, `resolve_model`, `ProviderNotConfigured`,
   `PromptSpec` + `PROMPT_SPECS`, `TOOLS`, `build_agent`, `collect_inputs`, `prepare_prompts`, `run_pipeline`,
   `persist_results`.

   ```python
   @dataclass(frozen=True)
   class PromptSpec:
       name: str
       template: str
       tier: str                       # "cheap" | "strong"
       output_type: Any
       parent: str | None = None       # name of the parent prompt
       stage: int = 1                  # 0 = parent, 1 = needs parent, 2 = needs stage-1 siblings
       tools: tuple[str, ...] = ()
       template_vars: dict[str, Any] = field(default_factory=dict)

   PROMPT_SPECS: list[PromptSpec] = [
       PromptSpec(
           name="job_analysis",
           template="templates/job_analysis.md",
           tier="cheap",
           output_type=JobAnalysis,
           stage=0,
           tools=("get_job_description",),
       ),
       PromptSpec(
           name="csl",
           template="templates/csl.md",
           tier="cheap",
           output_type=list[str],
           parent="job_analysis",
           stage=1,
       ),
   ]
   ```

   The run loop walks `PROMPT_SPECS` by stage; each stage runs concurrently under the semaphore, and a
   stage-N spec sees the stage N-1 outputs in `results` (and `deps.work_summaries` for the `header` case).

5. **`job_applications/tasks.py`** — add the `generate_prompts` celery task (sync wrapper + `asyncio.run`).

6. **`job_applications/admin.py`** — "Regenerate prompts" action dispatches the task with `force=True`;
   show `Prompt.template` and `Prompt.error`; add `PromptProvider` help text describing url/headers/name
   semantics.

7. **Templates** — new `templates/job_analysis.md`; extend `templates/csl.md` with the parent-context vars
   (the other templates are yours to extend).

8. **Management command** — replace `rengen_prompts.py` with `generate_prompts.py` (dispatch the task);
   update the `prompts:` target in `application_manager/Makefile` to `generate_prompts`.

9. **Migration** — `Prompt.template`, `Prompt.error`.

10. **Tests** — `job_applications/tests.py` (currently an empty stub): pipeline test with a stubbed model
   (`pydantic_ai.models.test.TestModel` / `FunctionModel`, monkeypatched over `ai.resolve_model`) — asserts
   the parent row is created first, the child's `parent` FK points at it, the child's rendered description
   contains the parent's data, the child's response is comma-joined, and the cheap tier was used. No network,
   no API key.

## Adding the remaining prompts (your part)

For each prompt:

1. **Template** — write `templates/<name>.md`. Keep the current prompt text as the base and add the parent
   context vars you need (`{{ job_analysis.responsibilities | join('; ') }}`,
   `{{ job_analysis.keywords | join(', ') }}`, ...).
2. **Spec** — add a `PromptSpec` to `PROMPT_SPECS`: name, template, tier (`"cheap"` for extraction/lists,
   `"strong"` for prose), `output_type` (`list[str]`, `str`, or a `BaseModel`), `parent` (`"job_analysis"`),
   `stage` (1 unless it consumes siblings), `tools`, and `template_vars` (e.g. `{"skill_type": "frontend"}`).
3. **Tool** — if the prompt needs a document, add a tool to `TOOLS` that reads it from `PipelineDeps`.
4. **Response shape** — `str` -> prose, `list[str]` -> comma-joined, `BaseModel` -> JSON dump. `build_pdf()`
   expects prose for `header`/blurb/`job_name` and comma-separated for `csl`/skills.

Remaining prompts, with the values to use:

| prompt | tier | output_type | template | tools | stage |
| --- | --- | --- | --- | --- | --- |
| `job_name` | cheap | `str` | `templates/job_name.md` | — | 1 |
| `frontend` | cheap | `list[str]` | `templates/skills_list.md` | `get_skill_list` | 1 |
| `backend` | cheap | `list[str]` | `templates/skills_list.md` | `get_skill_list` | 1 |
| `database` | cheap | `list[str]` | `templates/skills_list.md` | `get_skill_list` | 1 |
| `infrastructure` | cheap | `list[str]` | `templates/skills_list.md` | `get_skill_list` | 1 |
| `bvs.md` | strong | `str` | `templates/job_blurb.md` | `get_job_history` | 1 |
| `staffbase.md` | strong | `str` | `templates/job_blurb.md` | `get_job_history` | 1 |
| `10SPD.md` | strong | `str` | `templates/job_blurb.md` | `get_job_history` | 1 |
| `header` | strong | `str` | `templates/resume_header.md` | `get_work_summaries` | 2 |

Notes for the tricky ones:

- The skills prompts share one template, so the skill type must reach the template: put it in
  `template_vars` (`{"skill_type": "frontend"}`) and use it in the template body.
- The blurbs share one template; bind the company via `template_vars` (`{"company_key": "bvs.md"}`) so the
  `get_job_history` tool returns the right document deterministically.
- `header` runs in stage 2: after stage 1 completes, fill `deps.work_summaries` with the finished blurbs so
  `get_work_summaries()` can return them. `Prompt.parent` stays `job_analysis` for every child — the FK is
  single-valued and the blurbs are siblings of `header`, not its parent.

## Known consequence of the partial implementation

`build_pdf()` reads `header`, `csl`, the 4 skill prompts and the 3 blurb prompts, and raises when a prompt is
missing (`get_prompt()` throws). Until the remaining 9 prompts are implemented, PDF generation for an
application will fail on the missing prompts. Either implement them first, or make `build_pdf()` skip missing
prompts (`get_prompt(name, error=False)` already supports that) — the latter is a one-line-per-prompt change
but changes the output shape, so prefer finishing the prompts.

## Acceptance criteria mapping

| Criterion | How | Demonstrated by the example |
| --- | --- | --- |
| pydantic_ai for prompting + tool management | `Agent` per prompt with `output_type`, `@agent.tool` for `get_job_description` | yes |
| no dynamic or external configs, just functions inside task(s) | tier routing, provider resolution and rendering are code; the only DB-driven lookup is provider credentials/endpoints | yes |
| delegate simple / basic prompts to cheaper providers | `PromptSpec.tier` sends extraction/list prompts to `CHEAP_MODEL`, prose to `STRONG_MODEL` | cheap tier yes; strong tier wired, exercised once you add a prose prompt |

## Risks / open items

1. **OpenAI-compatible wire format assumption** for all `PromptProvider` rows — a native Anthropic endpoint will
   not work. Would need a `kind` column if that changes.
2. **`STRONG_MODEL`/`CHEAP_MODEL` are code constants** that must match `PromptProvider.name` values; a missing
   row raises `ProviderNotConfigured` listing the configured names.
3. **Cost** — the example costs 2 calls per application (~1 cheap parent + 1 cheap child); the full set is
   ~11. Auto-dispatch on every description edit multiplies that.
4. `Prompt.description` now embeds parent data, so it gets long in the admin view.
5. The pipeline upserts `Prompt` rows by name, matching today's `get_prompt` behaviour; existing rows are
   updated in place.
6. Existing `Prompt.response` rows keep their current format; no data migration needed.
7. Dynamic tool registration (`agent.tool(fn)` on an existing agent) must be verified against the installed
   pydantic-ai version; if the direct-call form is not supported, declare the tools with the decorator inside
   each agent factory.
