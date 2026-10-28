"""Single-call resume tuning pipeline with system-query tools.

The model receives one instruction plus a set of tools that read named
resources (the application row, supporting documents, the base resume) and
TinyFish-backed company research. It returns one JSON Resume document, which is
merged over the base resume, validated against the vendored schema, and stored
on `Application.tuning`.
"""

import copy
import json
import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import jsonschema
from django.conf import settings
from django.utils import timezone
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from . import services
from .models import (
    Application,
    Company,
    Prompt,
    PromptProvider,
    SkillType,
    SKILL_PATHS,
    SKILL_TYPE_TO_RESUME_NAME,
    HISTORY_PATHS,
    read_supporting_document,
)


logger = logging.getLogger(__name__)


RESEARCH_TTL = timedelta(days=7)
RESEARCH_UNAVAILABLE_NO_KEY = (
    "Company research unavailable (no API key configured)."
)


# ---------------------------------------------------------------------------
# JSON Resume model (mirrors json-resume-api/schema.json)
# ---------------------------------------------------------------------------


class _PermissiveModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Location(_PermissiveModel):
    address: str | None = None
    postalCode: str | None = None
    city: str | None = None
    countryCode: str | None = None
    region: str | None = None


class Profile(_PermissiveModel):
    network: str | None = None
    username: str | None = None
    url: str | None = None


class Basics(_PermissiveModel):
    name: str | None = None
    label: str | None = None
    image: str | None = None
    email: str | None = None
    phone: str | None = None
    url: str | None = None
    summary: str | None = None
    location: Location | None = None
    profiles: list[Profile] | None = None


class Work(_PermissiveModel):
    name: str | None = None
    location: str | None = None
    description: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Volunteer(_PermissiveModel):
    organization: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Education(_PermissiveModel):
    institution: str | None = None
    url: str | None = None
    area: str | None = None
    studyType: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    score: str | None = None
    courses: list[str] | None = None


class Award(_PermissiveModel):
    title: str | None = None
    date: str | None = None
    awarder: str | None = None
    summary: str | None = None


class Certificate(_PermissiveModel):
    name: str | None = None
    date: str | None = None
    url: str | None = None
    issuer: str | None = None


class Publication(_PermissiveModel):
    name: str | None = None
    publisher: str | None = None
    releaseDate: str | None = None
    url: str | None = None
    summary: str | None = None


class Skill(_PermissiveModel):
    name: str | None = None
    level: str | None = None
    keywords: list[str] | None = None


class Language(_PermissiveModel):
    language: str | None = None
    fluency: str | None = None


class Interest(_PermissiveModel):
    name: str | None = None
    keywords: list[str] | None = None


class Reference(_PermissiveModel):
    name: str | None = None
    reference: str | None = None


class Project(_PermissiveModel):
    name: str | None = None
    description: str | None = None
    highlights: list[str] | None = None
    keywords: list[str] | None = None
    startDate: str | None = None
    endDate: str | None = None
    url: str | None = None
    roles: list[str] | None = None
    entity: str | None = None
    type: str | None = None


class Meta(_PermissiveModel):
    canonical: str | None = None
    version: str | None = None
    lastModified: str | None = None


class ResumeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str | None = Field(default=None, alias="$schema")
    basics: Basics | None = None
    work: list[Work] | None = None
    volunteer: list[Volunteer] | None = None
    education: list[Education] | None = None
    awards: list[Award] | None = None
    certificates: list[Certificate] | None = None
    publications: list[Publication] | None = None
    skills: list[Skill] | None = None
    languages: list[Language] | None = None
    interests: list[Interest] | None = None
    references: list[Reference] | None = None
    projects: list[Project] | None = None
    meta: Meta | None = None
    payload: str | None = None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@dataclass
class PipelineDeps:
    """Everything the tools may read."""

    job_description: str
    company: str
    notes: str = ""
    company_research: str | None = None


def get_job_description(ctx: RunContext[PipelineDeps]) -> str:
    """Return the job description of the posting being processed."""
    return ctx.deps.job_description


def get_notes(ctx: RunContext[PipelineDeps]) -> str:
    """Return my notes/interview questions for this application."""
    return ctx.deps.notes


def get_history(ctx: RunContext[PipelineDeps], company: Company) -> str:
    """Return my work history for the given company."""
    return read_supporting_document(HISTORY_PATHS[company])


def get_skills(ctx: RunContext[PipelineDeps], skill_type: SkillType) -> str:
    """Return my skills for the given skill type."""
    return read_supporting_document(SKILL_PATHS[skill_type])


def get_resume(ctx: RunContext[PipelineDeps]) -> str:
    """Return the current JSON Resume document."""
    return read_supporting_document("supporting_documents/json-resume.json")


def search_company(query: str):
    """Run a TinyFish web search for the company."""
    from tinyfish import TinyFish

    client = TinyFish(api_key=os.environ["TINYFISH_API_KEY"], timeout=60)
    return client.search.query(
        query=query,
        purpose="company background for resume tailoring",
    )


def fetch_pages(urls: list[str]):
    """Fetch and extract the text of the given pages through TinyFish."""
    from tinyfish import TinyFish

    client = TinyFish(api_key=os.environ["TINYFISH_API_KEY"], timeout=60)
    return client.fetch.get_contents(
        urls=urls,
        format="markdown",
        purpose="company background for resume tailoring",
    )


def build_company_brief(company: str) -> str:
    """Build a short, source-backed company brief through TinyFish."""
    if not os.getenv("TINYFISH_API_KEY"):
        return RESEARCH_UNAVAILABLE_NO_KEY

    try:
        query = (
            f"{company} company overview products engineering blog recent news"
        )
        search = search_company(query)
        urls = [result.url for result in search.results[:5] if result.url]
        pages = fetch_pages(urls[:4]) if urls else None

        parts = [f"# {company} research"]
        if pages is not None:
            for result in pages.results:
                text = (result.text or "")[:3000]
                parts.append(
                    f"## {result.title or result.url}\n"
                    f"Source: {result.url}\n{text}"
                )
            for error in pages.errors:
                parts.append(f"- could not fetch {error.url}: {error.error}")
        else:
            for result in search.results[:5]:
                parts.append(f"- {result.title} ({result.url}): {result.snippet}")

        brief = "\n\n".join(parts)[:10000]
        return f"<company_research>\n{brief}\n</company_research>"
    except Exception as exc:
        logger.exception("company research failed for %s", company)
        return f"Company research unavailable: {exc}."


def research_company(ctx: RunContext[PipelineDeps]) -> str:
    """Return the company brief already stored on the application.

    The crawl runs before the agent starts, so this tool only reads the value
    loaded into deps from `Application.company_research`.
    """
    return ctx.deps.company_research or "Company research unavailable."


TOOLS = (
    get_job_description,
    get_notes,
    get_history,
    get_skills,
    get_resume,
    research_company,
)


# ---------------------------------------------------------------------------
# Merge and validation
# ---------------------------------------------------------------------------


_LIST_KEY_FIELDS = {
    "work": "name",
    "volunteer": "organization",
    "education": "institution",
    "awards": "title",
    "certificates": "name",
    "publications": "name",
    "skills": "name",
    "languages": "language",
    "interests": "name",
    "references": "name",
    "projects": "name",
    "profiles": "network",
}


def _merge_list(base: list, patch: list, key_field: str) -> list:
    if not patch:
        return copy.deepcopy(base)

    merged = copy.deepcopy(base) if isinstance(base, list) else []
    for item in patch:
        key = item.get(key_field) if isinstance(item, dict) else None
        if key is not None:
            for index, existing in enumerate(merged):
                if isinstance(existing, dict) and existing.get(key_field) == key:
                    merged[index] = merge_resume(existing, item)
                    break
            else:
                merged.append(copy.deepcopy(item))
        else:
            merged.append(copy.deepcopy(item))
    return merged


def merge_resume(base: dict, patch: dict) -> dict:
    """Merge a model-produced patch over the base resume without dropping data."""
    if not isinstance(base, dict):
        base = {}

    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_resume(merged[key], value)
        elif isinstance(value, list):
            if value and not all(isinstance(item, dict) for item in value):
                merged[key] = copy.deepcopy(value)
            else:
                merged[key] = _merge_list(
                    merged.get(key, []),
                    value,
                    _LIST_KEY_FIELDS.get(key, "name"),
                )
        elif value is not None:
            merged[key] = value
    return merged


@lru_cache(maxsize=1)
def load_resume_schema() -> dict:
    path = (
        settings.BASE_DIR
        / "application_manager"
        / "supporting_documents"
        / "json-resume.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def validate_resume(blob: dict) -> None:
    """Validate a JSON Resume document against the vendored schema."""
    jsonschema.validate(
        blob,
        load_resume_schema(),
        format_checker=FormatChecker(),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


# One model (and therefore one HTTP client / connection pool) per provider per
# pipeline run. Cleared at the start of every run.
_model_cache: dict[tuple, Model] = {}


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


def build_agent(application: Application) -> Agent:
    """Build the single tuning agent for an application."""
    agent = Agent(
        _model_for(application.provider),
        deps_type=PipelineDeps,
        output_type=ResumeDocument,
    )
    for tool in TOOLS:
        agent.tool(tool)
    return agent


def collect_inputs(application_id: int) -> PipelineDeps:
    """Read the application and its cached company brief into deps."""
    application = Application.objects.get(pk=application_id)

    return PipelineDeps(
        job_description=application.description,
        company=application.company,
        notes=application.notes or "",
        company_research=application.company_research,
    )


def ensure_company_research(application: Application, force: bool = False) -> str:
    """Crawl the company before tuning, reusing a fresh cached brief."""
    fresh = (
        application.company_research
        and application.company_researched_at
        and application.company_researched_at >= timezone.now() - RESEARCH_TTL
    )
    if fresh and not force:
        return application.company_research

    brief = build_company_brief(application.company)
    application.company_research = brief
    application.company_researched_at = (
        None
        if brief.startswith("Company research unavailable")
        else timezone.now()
    )
    application.save()
    return brief


def prepare_run(application: Application) -> Prompt:
    """Upsert the application's single prompt row."""
    description = services.render_template(
        "templates/tuning.md",
        company=application.company,
        job_description=application.description,
        skill_names=SKILL_TYPE_TO_RESUME_NAME,
    )
    prompt, _created = Prompt.objects.update_or_create(
        application=application,
        defaults={
            "template": "templates/tuning.md",
            "description": description,
            "error": None,
        },
    )
    return prompt


def run_tuning(application_id: int, force: bool = False) -> ResumeDocument:
    """Run the single tuning call and persist its result."""
    application = Application.objects.get(pk=application_id)

    if not force and application.tuning:
        try:
            return ResumeDocument.model_validate(application.tuning)
        except Exception:
            pass

    _model_cache.clear()
    ensure_company_research(application, force=force)
    deps = collect_inputs(application_id)
    prompt = prepare_run(application)

    try:
        result = build_agent(application).run_sync(prompt.description, deps=deps)
        patch = result.output.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )
        base = json.loads(
            read_supporting_document("supporting_documents/json-resume.json")
        )
        merged = merge_resume(base, patch)
        validate_resume(merged)
    except Exception as exc:
        prompt.error = str(exc)
        prompt.save(update_fields=["error"])
        raise

    application.tuning = merged
    prompt.response = json.dumps(merged, indent=2)
    prompt.error = None

    application.save()
    prompt.save()

    return ResumeDocument.model_validate(merged)
