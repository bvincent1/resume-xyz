"""Prompt pipeline: turn a job posting into the `Prompt` rows the resume needs.

The pipeline is synchronous end to end. `Prompt.render()` uses pydantic-ai's
`run_sync`, so the pipeline must be driven from synchronous code (a Celery
worker, a management command, the Django shell) — never from inside a running
event loop.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from . import services
from .models import (
    Application,
    Prompt,
    PromptProvider,
    job_histories,
    read_supporting_document,
    skills_types,
)


logger = logging.getLogger(__name__)


# Prompt -> model tier routing (code, not config). These must match a
# `PromptProvider.name` row; a missing row raises `ProviderNotConfigured`.
STRONG_MODEL = "gpt-4.1"
CHEAP_MODEL = "gpt-4.1-mini"


class ProviderNotConfigured(Exception):
    """Raised when a tier maps to a `PromptProvider.name` that does not exist."""

    def __init__(self, name: str, configured: list[str]):
        self.name = name
        self.configured = configured
        super().__init__(
            f"PromptProvider {name!r} is not configured; "
            f"configured providers: {configured}"
        )


class JobAnalysis(BaseModel):
    """Typed output of the parent `job_analysis` prompt."""

    title: str
    seniority: str
    responsibilities: list[str]
    required_skills: list[str]
    keywords: list[str]


@dataclass
class PipelineDeps:
    """Everything the agents may read.

    Collected before the pipeline starts, so no tool ever touches the DB or the
    filesystem. `work_summaries` is filled in between stages for prompts that
    consume sibling output.
    """

    job_description: str
    company: str
    histories: dict[str, str] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    work_summaries: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptSpec:
    name: str
    template: str
    tier: str  # "cheap" | "strong"
    output_type: Any
    parent: str | None = None  # name of the parent prompt
    stage: int = 1  # 0 = parent, 1 = needs parent, 2 = needs stage-1 siblings
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
    PromptSpec(
        name="job_name",
        template="templates/job_name.md",
        tier="cheap",
        output_type=str,
        parent="job_analysis",
        stage=1,
    ),
    PromptSpec(
        name="frontend",
        template="templates/skills_list.md",
        tier="cheap",
        output_type=list[str],
        parent="job_analysis",
        stage=1,
        tools=("get_skill_list",),
        template_vars={"skill_type": "frontend"},
    ),
    PromptSpec(
        name="backend",
        template="templates/skills_list.md",
        tier="cheap",
        output_type=list[str],
        parent="job_analysis",
        stage=1,
        tools=("get_skill_list",),
        template_vars={"skill_type": "backend"},
    ),
    PromptSpec(
        name="database",
        template="templates/skills_list.md",
        tier="cheap",
        output_type=list[str],
        parent="job_analysis",
        stage=1,
        tools=("get_skill_list",),
        template_vars={"skill_type": "database"},
    ),
    PromptSpec(
        name="infrastructure",
        template="templates/skills_list.md",
        tier="cheap",
        output_type=list[str],
        parent="job_analysis",
        stage=1,
        tools=("get_skill_list",),
        template_vars={"skill_type": "infrastructure"},
    ),
    PromptSpec(
        name="bvs.md",
        template="templates/job_blurb.md",
        tier="strong",
        output_type=str,
        parent="job_analysis",
        stage=1,
        tools=("get_job_history",),
        template_vars={"company_key": "bvs.md"},
    ),
    PromptSpec(
        name="staffbase.md",
        template="templates/job_blurb.md",
        tier="strong",
        output_type=str,
        parent="job_analysis",
        stage=1,
        tools=("get_job_history",),
        template_vars={"company_key": "staffbase.md"},
    ),
    PromptSpec(
        name="10SPD.md",
        template="templates/job_blurb.md",
        tier="strong",
        output_type=str,
        parent="job_analysis",
        stage=1,
        tools=("get_job_history",),
        template_vars={"company_key": "10SPD.md"},
    ),
    PromptSpec(
        name="header",
        template="templates/resume_header.md",
        tier="strong",
        output_type=str,
        parent="job_analysis",
        stage=2,
        tools=("get_work_summaries",),
    ),
]

SPECS_BY_NAME: dict[str, PromptSpec] = {spec.name: spec for spec in PROMPT_SPECS}


def get_job_description(ctx: RunContext[PipelineDeps]) -> str:
    """Return the job description of the posting being processed."""
    return ctx.deps.job_description


def get_skill_list(ctx: RunContext[PipelineDeps], skill_type: str) -> str:
    """Return my skills for the given skill type.

    Valid skill types: frontend, backend, database, infrastructure.
    """
    return ctx.deps.skills.get(skill_type, "")


def get_job_history(ctx: RunContext[PipelineDeps], company_key: str) -> str:
    """Return my work history document for the given company key."""
    return ctx.deps.histories.get(company_key, "")


def get_work_summaries(ctx: RunContext[PipelineDeps]) -> str:
    """Return the finished work-history blurbs, keyed by company."""
    return json.dumps(ctx.deps.work_summaries, indent=2)


TOOLS = {
    "get_job_description": get_job_description,
    "get_skill_list": get_skill_list,
    "get_job_history": get_job_history,
    "get_work_summaries": get_work_summaries,
}


# One model (and therefore one HTTP client / connection pool) per provider per
# pipeline run. Cleared at the start of every run.
_model_cache: dict[tuple, Model] = {}


def find_provider(name: str) -> PromptProvider:
    """Look up a PromptProvider row by name."""
    provider = PromptProvider.objects.filter(name=name).first()
    if provider is None:
        raise ProviderNotConfigured(
            name, list(PromptProvider.objects.values_list("name", flat=True))
        )
    return provider


def _model_for(provider: PromptProvider) -> Model:
    key = (
        provider.pk,
        provider.name,
        provider.url,
        json.dumps(provider.headers or {}, sort_keys=True),
    )
    model = _model_cache.get(key)
    if model is None:
        model = services.build_model(provider.name, provider.url, provider.headers)
        _model_cache[key] = model
    return model


def build_agent(prompt: Prompt) -> Agent:
    """Build the agent for a prompt row.

    The agent uses the model of the provider bound to the row plus the output
    type and tools of the row's spec.
    """
    spec = SPECS_BY_NAME[prompt.name]
    model = _model_for(prompt.provider)
    agent = Agent(model, deps_type=PipelineDeps, output_type=spec.output_type)
    for tool_name in spec.tools:
        agent.tool(TOOLS[tool_name])
    return agent


def collect_inputs(application_id: int) -> PipelineDeps:
    """Read the application and supporting documents into a `PipelineDeps`."""
    application = Application.objects.get(pk=application_id)
    return PipelineDeps(
        job_description=application.description,
        company=application.company,
        histories={
            doc.split("/")[-1]: read_supporting_document(doc) for doc in job_histories
        },
        skills={
            skill_type: read_supporting_document(
                f"supporting_documents/{skill_type}_skills.md"
            )
            for skill_type in skills_types
        },
    )


def prepare_prompts(application_id: int) -> dict[str, Prompt]:
    """Upsert one `Prompt` row per spec (template, parent, provider)."""
    application = Application.objects.get(pk=application_id)
    providers: dict[str, PromptProvider] = {}
    prompts: dict[str, Prompt] = {}
    for spec in PROMPT_SPECS:
        tier_name = CHEAP_MODEL if spec.tier == "cheap" else STRONG_MODEL
        provider = providers.get(tier_name)
        if provider is None:
            provider = find_provider(tier_name)
            providers[tier_name] = provider
        prompt, _created = Prompt.objects.update_or_create(
            application=application,
            name=spec.name,
            defaults={
                "template": spec.template,
                "provider": provider,
                "parent": prompts.get(spec.parent),
                "error": None,
            },
        )
        prompts[spec.name] = prompt
    return prompts


def _parse_parent(parent_name: str, response: str | None):
    if response is None:
        return None
    output_type = SPECS_BY_NAME[parent_name].output_type
    if isinstance(output_type, type) and issubclass(output_type, BaseModel):
        return output_type.model_validate_json(response)
    return response


def build_context(spec: PromptSpec, deps: PipelineDeps, results: dict) -> dict:
    """Build the Jinja context for a prompt: shared inputs, vars and parent data."""
    context: dict[str, Any] = {
        "job_description": deps.job_description,
        "company": deps.company,
        **spec.template_vars,
    }
    if spec.parent:
        context[spec.parent] = _parse_parent(spec.parent, results.get(spec.parent))
    return context


def run_pipeline(
    deps: PipelineDeps, prompts: dict[str, Prompt], force: bool = False
) -> dict:
    """Run every prompt in stage order, one at a time."""
    _model_cache.clear()
    results: dict[str, str] = {}
    for stage in sorted({spec.stage for spec in PROMPT_SPECS}):
        for spec in (s for s in PROMPT_SPECS if s.stage == stage):
            prompt = prompts[spec.name]
            context = build_context(spec, deps, results)
            rendered = services.render_template(spec.template, **context)
            if not force and prompt.response and prompt.description == rendered:
                results[spec.name] = prompt.response
                continue
            try:
                prompt.render(deps, **context)
                results[spec.name] = prompt.response
            except Exception as exc:
                prompt.error = str(exc)
                logger.exception("prompt %s failed", spec.name)
        # Stage-N outputs feed the tools of later stages (e.g. header blurbs).
        for name, value in results.items():
            if name in deps.histories:
                deps.work_summaries[name] = value
    return results


def persist_results(prompts: dict[str, Prompt]) -> None:
    """Save every prompt row (description + response + error)."""
    for prompt in prompts.values():
        prompt.save()
