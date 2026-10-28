import base64
import copy
import json
import logging
from enum import Enum
from urllib.parse import urlencode

from django.db import models, transaction

from .services import (
    generate_pdf,
    read_supporting_document,
    render_string,
    render_template,
)


logger = logging.getLogger(__name__)

RESUME_SCHEMA_URL = (
    "https://github.com/bvincent1/resume-xyz/raw/refs/heads/json-resume/"
    "json-resume-api/schema.json"
)


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


class ApplicationStatus(models.Model):
    name = models.CharField(blank=False, null=False)

    def __str__(self):
        return self.name

    @classmethod
    def get_default_pk(cls):
        status, _created = cls.objects.get_or_create(
            name="todo",
            defaults=dict(name="todo"),
        )
        return status.pk


class Application(models.Model):
    title = models.CharField(blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    status = models.ForeignKey(
        ApplicationStatus,
        null=False,
        blank=False,
        on_delete=models.PROTECT,
        default=ApplicationStatus.get_default_pk,
    )
    company = models.CharField(null=False, blank=False, default="")
    job_url = models.URLField(blank=True, null=True)
    resume_url = models.URLField(blank=True, null=True)
    last_scanned_requests = models.DateTimeField(null=True)
    last_scanned_browserless = models.DateTimeField(null=True)

    created = models.DateTimeField(null=False, auto_now_add=True)
    updated = models.DateTimeField(null=False, auto_now=True)
    notes = models.TextField(
        null=True,
        blank=True,
        default=read_supporting_document(
            "supporting_documents/1st_interview_questions.md"
        ),
    )
    include_project_management = models.BooleanField(
        default=True, null=False, blank=False
    )
    include_databricks = models.BooleanField(default=True, null=False, blank=False)

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

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        if self.company:
            return f"{self.company} * {self.title} - {self.status}"
        return f"{self.title} - {self.status}"

    def _prompt_inputs_changed(self) -> bool:
        """Return True when the fields the prompts are built from changed."""
        if self._state.adding or self.pk is None:
            return True
        stored = (
            Application.objects.filter(pk=self.pk)
            .values("description", "title", "company")
            .first()
        )
        if stored is None:
            return True
        return (
            stored["description"] != self.description
            or stored["title"] != self.title
            or stored["company"] != self.company
        )

    def save(self, **kwargs):
        dispatch = False  # self._prompt_inputs_changed()
        super().save(**kwargs)
        if dispatch:
            from .tasks import dispatch_generate_prompts

            transaction.on_commit(lambda: dispatch_generate_prompts(self.pk))

    def list_prompts(self):
        try:
            prompt = self.prompt
        except Prompt.DoesNotExist:
            return []
        return [f"{prompt.description}\n{prompt.response}\n"]

    def build_pdf(self):
        api_url = (
            "https://egxtrrqutcvobbehvlep.supabase.co/functions/v1/log-get-request-time"
        )
        base = json.loads(
            read_supporting_document("supporting_documents/json-resume.json")
        )
        resume = copy.deepcopy(base)

        if self.tuning:
            try:
                from .ai import validate_resume

                validate_resume(self.tuning)
                resume = copy.deepcopy(self.tuning)
            except Exception:
                logger.warning(
                    "invalid tuning blob for application %s; using base resume",
                    self.pk,
                    exc_info=True,
                )

        resume["$schema"] = RESUME_SCHEMA_URL

        # Resolve an item in a list section by case-insensitive field match, so
        # section targeting does not depend on the order of entries.
        def _find(section, **fields):
            wanted = {k: str(v).lower() for k, v in fields.items()}
            for item in resume.get(section, []) or []:
                if all(
                    str(item.get(k, "")).lower() == v for k, v in wanted.items()
                ):
                    return item
            return None

        breakout = render_template(
            "templates/breakout.md",
            url=f"{api_url}?{urlencode({'company': self.company, 'method': 'url' })}",
            base_64_url=f"{base64.b64encode(f"{api_url}?{urlencode({'company': self.company, 'method': 'base64'})}".encode("ascii")).decode("ascii")}",
        )

        if resume.get("payload"):
            resume["payload"] = render_template(
                "templates/payload.html",
                csl=resume["payload"],
                breakout=breakout,
            )

        basics = resume.get("basics") or {}
        resume["basics"] = basics

        github_url = "https://github.deuterium.dev"
        gitlab_url = "https://gitlab.deuterium.dev"
        linkedin_url = "https://linkedin.deuterium.dev"
        coursera_url = "https://coursera.deuterium.dev"

        query_params = urlencode(
            {"company": self.company, "method": "resume", "app": self.pk}
        )

        for profile in basics.get("profiles", []) or []:
            network = (profile.get("network") or "").lower()
            if network == "linkedin":
                profile["url"] = f"{linkedin_url}?{query_params}"
            elif network == "github":
                profile["url"] = f"{github_url}?{query_params}"
            elif network == "gitlab":
                profile["url"] = f"{gitlab_url}?{query_params}"

        coursera = _find("certificates", issuer="Google Coursera")
        if coursera is not None:
            coursera["url"] = f"{coursera_url}?{query_params}"

        basics["email"] = f"benjc.vincent+{self.pk}@gmail.com"

        if not self.include_project_management:
            cert = _find("certificates", name="Project Management")
            if cert is not None:
                resume["certificates"].remove(cert)
        if not self.include_databricks:
            cert = _find("certificates", issuer="Databricks")
            if cert is not None:
                resume["certificates"].remove(cert)

        self.resume_url = generate_pdf(resume)
        self.save()

        return self.resume_url

    def delete(self):
        return super().delete()


class PromptProvider(models.Model):
    name = models.CharField(
        blank=False,
        null=False,
        unique=True,
        help_text=(
            "Model id sent to the API, e.g. 'openai/gpt-4.1'. Selected per "
            "application through Application.provider."
        ),
    )
    url = models.URLField(
        blank=False,
        null=False,
        help_text="OpenAI-compatible base URL, e.g. 'https://openrouter.ai/api/v1'.",
    )
    env_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Environment variable holding the provider API key, e.g. "
            "'OPENROUTER_API_KEY'."
        ),
    )
    headers = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Additional HTTP headers sent with every request. Auth comes from "
            "`env_key`, not from this mapping."
        ),
    )

    def __str__(self):
        return self.name

    def render_headers(self):
        return json.loads(render_string(json.dumps(self.headers)))


class Prompt(models.Model):
    description = models.TextField(blank=False, null=False)
    application = models.OneToOneField(
        Application,
        null=False,
        on_delete=models.CASCADE,
        related_name="prompt",
    )
    template = models.CharField(blank=True, default="")
    response = models.TextField(blank=True, null=True)
    notes = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.application.company} -> tuning"

    def get_trimmed_response(self):
        # used in the admin dashboard table
        if self.response is not None:
            return self.response[:10]
        return ""


class URLStatus(models.Model):
    name = models.CharField(blank=False, null=False)

    def __str__(self):
        return self.name


class JobURL(models.Model):
    url = models.URLField(unique=True, blank=False, null=False)
    status = models.ForeignKey(
        URLStatus,
        null=False,
        blank=False,
        on_delete=models.PROTECT,
        # default=URLStatus.objects.get(name="todo"),
    )

    def __str__(self):
        return f"{self.status}-{self.url}"
