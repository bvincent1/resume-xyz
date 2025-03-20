from django.db import models
from jinja2 import Environment, PackageLoader, select_autoescape
import json
from django.conf import settings
import os

from .services import ResumeService

PROJECT_DIR = settings.BASE_DIR.as_posix()

env = Environment(
    loader=PackageLoader(
        package_name="application_manager",
        package_path=PROJECT_DIR + "/application_manager/templates",
    ),
    autoescape=select_autoescape(),
)

job_histories = [
    "/application_manager/supporting_documents/histories/tms.md",
    "/application_manager/supporting_documents/histories/staffbase.md",
    "/application_manager/supporting_documents/histories/bvs.md",
    "/application_manager/supporting_documents/histories/10SPD.md",
]


class ApplicationStatus(models.Model):
    name = models.CharField(blank=False, null=False)

    def __str__(self):
        return self.name


class Application(models.Model):
    title = models.CharField(blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    status = models.ForeignKey(
        ApplicationStatus,
        null=False,
        blank=False,
        on_delete=models.PROTECT,
        default=ApplicationStatus.objects.get(name="todo"),
    )
    company = models.CharField(null=False, blank=False, default="")

    job_url = models.URLField(blank=True, null=True)
    resume_url = models.URLField(blank=True, null=True)

    created = models.DateTimeField(null=False, auto_now_add=True)
    updated = models.DateTimeField(null=False, auto_now=True)

    def __str__(self):
        if self.company:
            return f"{self.company} * {self.title} - {self.status}"
        return f"{self.title} - {self.status}"

    def save(self, **kwargs):
        super().save(**kwargs)
        self.generate_all_prompts()

    def generate_job_histories_prompts(self):
        for doc in job_histories:
            with open(PROJECT_DIR + doc, "r") as f:
                name = doc.split("/")[-1]
                try:
                    p = self.get_prompt(name)
                    p.description = env.get_template("job_blurb.md").render(
                        job_description=self.description,
                        job_tasks_list=[l.strip() for l in f.readlines()],
                    )
                    p.save()
                except:
                    Prompt(
                        description=env.get_template("job_blurb.md").render(
                            job_description=self.description,
                            job_tasks_list=[l.strip() for l in f.readlines()],
                        ),
                        application=self,
                        name=name,
                    ).save()

    def generate_payload_prompt(self):
        try:
            p = self.get_prompt("csl")
            p.description = env.get_template("csl.md").render(
                job_description=self.description,
            )
            p.save()
        except:

            Prompt(
                description=env.get_template("csl.md").render(
                    job_description=self.description,
                ),
                application=self,
                name="csl",
            ).save()

    def generate_header_prompt(self):
        jobs = [open(PROJECT_DIR + h, "r").read() for h in job_histories]
        try:
            p = self.get_prompt("header")
            p.description = env.get_template("resume_header.md").render(
                job_description=self.description,
                job_histories=jobs,
            )
            p.save()
        except:
            Prompt(
                description=env.get_template("resume_header.md").render(
                    job_description=self.description,
                    job_histories=jobs,
                ),
                application=self,
                name="header",
            ).save()

    def list_prompts(self):
        return [
            f"{p.name} >\n{p.description}\n{p.response}\n" for p in self.prompts.all()
        ]

    def generate_all_prompts(self):
        self.generate_job_histories_prompts()
        self.generate_payload_prompt()
        self.generate_header_prompt()

    def get_prompt(self, name):
        return self.prompts.get(name__exact=name)

    def build_pdf(self):
        with open(PROJECT_DIR + "/../resume.json", "r") as fp:
            resume = json.load(fp)
            resume["basics"]["payload"] = env.get_template("payload.html").render(
                csl=self.get_prompt("csl").response,
            )
            resume["sections"]["summary"][
                "content"
            ] = f"<p>{self.get_prompt("header"
            ).response}</p>"

            for i in range(len(job_histories)):
                resume["sections"]["experience"]["items"][i][
                    "summary"
                ] = f"<p>{self.get_prompt(
                    job_histories[i].split("/")[-1]
                ).response}</p>"

            rs = ResumeService(
                username=os.getenv("RESUME_USERNAME"),
                password=os.getenv("RESUME_PASSWORD"),
            )
            resume_id = rs.create()
            rs.update(resume_id, resume)
            self.resume_url = rs.get_pdf_url(resume_id)
            self.save()

            return self.resume_url


class Prompt(models.Model):
    description = models.TextField(blank=False, null=False)
    application = models.ForeignKey(
        Application,
        null=False,
        on_delete=models.CASCADE,
        related_name="prompts",
    )
    name = models.CharField(blank=False, null=False)
    response = models.TextField(blank=True, null=True)

    def __str__(self):
        print(self.application)
        return f"{self.application.title} -> {self.name}"
