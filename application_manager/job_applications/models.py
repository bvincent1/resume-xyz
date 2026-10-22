from django.conf import settings
from django.db import models, transaction
from pydantic import BaseModel
import json
import base64
from urllib.parse import urlencode

from .services import FileService, render_pdf, render_template


job_histories = [
    "supporting_documents/histories/bvs.md",
    # "supporting_documents/histories/tms.md",
    "supporting_documents/histories/staffbase.md",
    "supporting_documents/histories/10SPD.md",
]

skills_types = [
    "frontend",
    "backend",
    "database",
    "infrastructure",
]


def read_supporting_document(path):
    """Read a supporting document from the local filesystem.

    ``path`` mirrors the S3 key previously used and is relative to the Django
    project directory, e.g. ``supporting_documents/histories/bvs.md``.
    """
    return (settings.BASE_DIR / "application_manager" / path).read_text(
        encoding="utf-8"
    )


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
        default=ApplicationStatus.get_default_pk(),
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
        dispatch = self._prompt_inputs_changed()
        super().save(**kwargs)
        if dispatch:
            from .tasks import dispatch_generate_prompts

            transaction.on_commit(lambda: dispatch_generate_prompts(self.pk))

    def list_prompts(self):
        return [
            f"{p.name} >\n{p.description}\n{p.response}\n" for p in self.prompts.all()
        ]

    def get_prompt(self, name, error=True):
        try:
            return self.prompts.get(name__exact=name)
        except:
            if error:
                raise Exception(f"prompt error trying to get: {name}")
            else:
                return None

    def build_pdf(self):
        api_url = (
            "https://egxtrrqutcvobbehvlep.supabase.co/functions/v1/log-get-request-time"
        )
        resume = json.loads(
            read_supporting_document("supporting_documents/json-resume.json")
        )
        breakout = render_template(
            "templates/breakout.md",
            url=f"{api_url}?{urlencode({'company': self.company, 'method': 'url' })}",
            base_64_url=f"{base64.b64encode(f"{api_url}?{urlencode({'company': self.company, 'method': 'base64'})}".encode("ascii")).decode("ascii")}",
        )
        resume["basics"]["payload"] = render_template(
            "templates/payload.html",
            csl=self.get_prompt("csl").response,
            breakout=breakout,
        )
        resume["basics"]["summary"] = self.get_prompt("header").response

        job_name_array = []
        # job name section
        if self.get_prompt("job_name", error=False) is not None:
            job_name_array = self.get_prompt("job_name").response.split(",")

        for i in range(len(job_name_array)):
            if job_name_array[i]:
                resume["work"][i]["position"] = job_name_array[i]

        ## link section

        # redirect_map = {
        #     '8d5fa094-0fa1-483a-902f-daf7f6b6ae7d': 'https://www.linkedin.com/in/vincent-slashsolve/',
        #     '8487a51c-7951-4e81-b5be-88ea49c7a4c8': 'https://github.com/bvincent1',
        #     '02b8c42f-f373-4f0d-8032-54d56f9121a9': 'https://gitlab.com/bvincent1',
        #     'e2fb9fdc-d30b-4f5e-bc9a-49998b722a3e': 'https://www.coursera.org/account/accomplishments/records/B3UH5Y6FNWKA'
        #   }

        github_url = "https://github.deuterium.dev"
        gitlab_url = "https://gitlab.deuterium.dev"
        linkedin_url = "https://linkedin.deuterium.dev"
        coursera_url = "https://coursera.deuterium.dev"

        query_params = urlencode(
            {"company": self.company, "method": "resume", "app": self.pk}
        )
        resume["basics"]["profiles"][0]["url"] = f"{linkedin_url}?{query_params}"

        resume["basics"]["profiles"][1]["url"] = f"{github_url}?{query_params}"

        resume["basics"]["profiles"][2]["url"] = f"{gitlab_url}?{query_params}"

        resume["certificates"][0]["url"] = f"{coursera_url}?{query_params}"

        resume["basics"]["email"] = f"benjc.vincent+{self.pk}@gmail.com"

        for i in range(len(job_histories)):
            resume["work"][i]["summary"] = self.get_prompt(
                job_histories[i].split("/")[-1]
            ).response

        for i in range(len(skills_types)):
            resume["skills"][i]["keywords"] = [
                k.strip()
                for k in (self.get_prompt(skills_types[i]).response or "").split(",")
            ]

        if not self.include_project_management:
            del resume["certificates"][0]
        if not self.include_databricks:
            del resume["certificates"][1]

        self.resume_url = render_pdf(resume)
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
            "Model id sent to the API, e.g. 'openai/gpt-4.1-mini'. The pipeline "
            "routes prompts to providers by this name (see CHEAP_MODEL / "
            "STRONG_MODEL in ai.py)."
        ),
    )
    url = models.URLField(
        blank=False,
        null=False,
        help_text="OpenAI-compatible base URL, e.g. 'https://openrouter.ai/api/v1'.",
    )
    headers = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "HTTP headers sent with every request, including "
            "'Authorization: Bearer <key>'."
        ),
    )

    def __str__(self):
        return self.name


class Prompt(models.Model):
    description = models.TextField(blank=False, null=False)
    application = models.ForeignKey(
        Application,
        null=False,
        on_delete=models.CASCADE,
        related_name="prompts",
    )
    name = models.CharField(blank=False, null=False)
    template = models.CharField(blank=True, default="")
    response = models.TextField(blank=True, null=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    provider = models.ForeignKey(
        PromptProvider,
        null=True,
        on_delete=models.SET_NULL,
        related_name="prompts",
    )
    notes = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.application.company} -> {self.name}"

    def render(self, deps, **context) -> str:
        """Template the description, ask the provider, and store the response.

        The instance is mutated in memory only — the caller saves it once the
        whole pipeline is done.
        """
        from .ai import build_agent  # local import: ai.py imports models.py

        self.description = render_template(self.template, **context)
        result = build_agent(self).run_sync(self.description, deps=deps)
        self.response = self.format_response(result.output)
        return self.response

    @staticmethod
    def format_response(output) -> str:
        """Render a model output into the text stored in ``response``."""
        if isinstance(output, BaseModel):
            return output.model_dump_json()
        if isinstance(output, list):
            return ", ".join(str(item) for item in output)
        return str(output)

    def get_trimmed_response(self):
        # used in the admin dashboard table
        if self.response is not None:
            return self.response[:10]
        return ""

    def save(self, **kwargs):
        super().save(**kwargs)
        # application_prompts = self.application.prompts.all()
        # if len(application_prompts) == len(
        #     [a for a in application_prompts if a.response != None]
        # ):
        #     self.application.status = ApplicationStatus.objects.get(name="ready")
        #     self.application.save()


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
