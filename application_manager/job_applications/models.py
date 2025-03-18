from django.db import models
from jinja2 import Environment, PackageLoader, select_autoescape
import os
from django.conf import settings

PROJECT_DIR = settings.BASE_DIR.as_posix()

env = Environment(
    loader=PackageLoader(
        package_name="application_manager",
        package_path=PROJECT_DIR + "/application_manager/templates",
    ),
    autoescape=select_autoescape(),
)

job_histories = [
    "/application_manager/supporting_documents/tms.md",
    "/application_manager/supporting_documents/bvs.md",
    "/application_manager/supporting_documents/staffbase.md",
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
    )

    url = models.URLField(blank=True, null=True)
    resume = models.FileField(blank=True, null=True)

    created = models.DateTimeField(null=False, auto_now_add=True)
    updated = models.DateTimeField(null=False, auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.created}"

    def save(self, **kwargs):
        super().save(**kwargs)

        for doc in job_histories:
            with open(PROJECT_DIR + doc, "r") as f:
                Prompt(
                    description=env.get_template("job_blurb.md").render(
                        job_description=self.description,
                        job_tasks_list=[l.strip() for l in f.readlines()],
                    ),
                    application=self,
                ).save()


class Prompt(models.Model):
    description = models.TextField(blank=False, null=False)
    application = models.ForeignKey(
        Application,
        null=False,
        on_delete=models.DO_NOTHING,
        related_name="prompts",
    )

    def __str__(self):
        return f"prompt {self.application.name}"
