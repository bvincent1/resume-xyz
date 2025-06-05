from django.db import models
from jinja2 import Environment, BaseLoader
import json
import os
import base64
from urllib.parse import urlencode

from .services import FileService, ResumeService


class S3Loader(BaseLoader):
    def get_source(self, env, template):
        return (
            FileService().open(template),
            template,
            lambda: False,
        )


env = Environment(
    loader=S3Loader(),
)

job_histories = [
    "supporting_documents/histories/tms.md",
    "supporting_documents/histories/staffbase.md",
    "supporting_documents/histories/bvs.md",
    "supporting_documents/histories/10SPD.md",
]

skills_types = [
    "frontend",
    "backend",
    "database",
    "infrastructure",
]


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
    resume_id = models.CharField(null=True, blank=True)

    job_url = models.URLField(blank=True, null=True)
    resume_url = models.URLField(blank=True, null=True)

    created = models.DateTimeField(null=False, auto_now_add=True)
    updated = models.DateTimeField(null=False, auto_now=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        if self.company:
            return f"{self.company} * {self.title} - {self.status}"
        return f"{self.title} - {self.status}"

    def save(self, **kwargs):
        super().save(**kwargs)
        self.generate_all_prompts()

    def generate_job_histories_prompts(self):
        f = FileService()
        for doc in job_histories:
            tasks_list = f.open(doc)
            name = doc.split("/")[-1]
            try:
                p = self.get_prompt(name)
                p.description = env.get_template("templates/job_blurb.md").render(
                    job_description=self.description,
                    job_tasks_list=tasks_list,
                )
                p.save()
            except:
                Prompt(
                    description=env.get_template("templates/job_blurb.md").render(
                        job_description=self.description,
                        job_tasks_list=tasks_list,
                    ),
                    application=self,
                    name=name,
                ).save()

    def generate_payload_prompt(self):
        try:
            p = self.get_prompt("csl")
            p.description = env.get_template("templates/csl.md").render(
                job_description=self.description,
            )
            p.save()
        except:
            Prompt(
                description=env.get_template("templates/csl.md").render(
                    job_description=self.description,
                ),
                application=self,
                name="csl",
            ).save()

    def generate_header_prompt(self):
        f = FileService()
        jobs = [f.open(h) for h in job_histories]
        try:
            p = self.get_prompt("header")
            p.description = env.get_template("templates/resume_header.md").render(
                job_description=self.description,
                job_histories=jobs,
            )
            p.save()
        except:
            Prompt(
                description=env.get_template("templates/resume_header.md").render(
                    job_description=self.description,
                    job_histories=jobs,
                ),
                application=self,
                name="header",
            ).save()

    def generate_skills_prompts(self):
        f = FileService()
        for skill_type in skills_types:
            skills_list = f.open(f"supporting_documents/{skill_type}_skills.md")
            try:
                p = self.get_prompt(skill_type)
                p.description = env.get_template("templates/skills_list.md").render(
                    job_description=self.description,
                    skill_type=skill_type,
                    skills_list=skills_list,
                )
                p.save()
            except:
                Prompt(
                    description=env.get_template("templates/skills_list.md").render(
                        job_description=self.description,
                        skill_type=skill_type,
                        skills_list=skills_list,
                        skill_count=4,
                    ),
                    application=self,
                    name=skill_type,
                ).save()

    def generate_job_name_prompt(self):
        prompt_name = "job_name"
        prompt_template = "templates/job_name.md"
        try:
            p = self.get_prompt(prompt_name)
            p.description = env.get_template(prompt_template).render(
                job_description=self.description,
            )
            p.save()
        except:
            Prompt(
                description=env.get_template(prompt_template).render(
                    job_description=self.description,
                ),
                application=self,
                name=prompt_name,
            ).save()

    def list_prompts(self):
        return [
            f"{p.name} >\n{p.description}\n{p.response}\n" for p in self.prompts.all()
        ]

    def generate_all_prompts(self):
        self.generate_job_histories_prompts()
        self.generate_payload_prompt()
        self.generate_header_prompt()
        self.generate_skills_prompts()
        self.generate_job_name_prompt()

    def get_prompt(self, name):
        try:
            return self.prompts.get(name__exact=name)
        except:
            print(name)
            raise Exception(f"prompt error trying to get: {name}")

    def build_pdf(self):
        f = FileService()
        api_url = (
            "https://egxtrrqutcvobbehvlep.supabase.co/functions/v1/log-get-request-time"
        )
        resume = json.loads(f.open("resume.json"))
        breakout = env.get_template("templates/breakout.md").render(
            url=f"{api_url}?{urlencode({'company': self.company, 'method': 'url' })}",
            base_64_url=f"{base64.b64encode(f"{api_url}?{urlencode({'company': self.company, 'method': 'base64'})}".encode("ascii")).decode("ascii")}",
        )
        resume["basics"]["payload"] = env.get_template("templates/payload.html").render(
            csl=self.get_prompt("csl").response,
            breakout=breakout,
        )
        resume["sections"]["summary"][
            "content"
        ] = f"<p>{self.get_prompt("header"
        ).response}</p>"

        # job name section
        job_name_array = self.get_prompt("job_name").response.split(",")

        resume["sections"]["experience"]["items"][0]["position"] = job_name_array[0]

        if len(job_name_array) >= 2 and job_name_array[1]:
            resume["sections"]["experience"]["items"][1]["position"] = job_name_array[1]
        # default to copying entry #0
        else:
            resume["sections"]["experience"]["items"][1]["position"] = job_name_array[0]

        if len(job_name_array) >= 3 and job_name_array[2]:
            resume["sections"]["experience"]["items"][2]["position"] = job_name_array[2]

        if len(job_name_array) >= 4 and job_name_array[3]:
            resume["sections"]["experience"]["items"][3]["position"] = job_name_array[3]

        if len(job_name_array) >= 5 and job_name_array[4]:
            resume["sections"]["experience"]["items"][4]["position"] = job_name_array[4]

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

        resume["sections"]["profiles"]["items"][0]["url"][
            "href"
        ] = f"{linkedin_url}?{urlencode({'company': self.company })}"
        
        resume["sections"]["profiles"]["items"][1]["url"][
            "href"
        ] = f"{github_url}?{urlencode({'company': self.company })}"

        resume["sections"]["profiles"]["items"][2]["url"][
            "href"
        ] = f"{gitlab_url}?{urlencode({'company': self.company })}"

        resume["sections"]["certifications"]["items"][0]["url"][
            "href"
        ] = f"{coursera_url}?{urlencode({'company': self.company })}"

        for i in range(len(job_histories)):
            resume["sections"]["experience"]["items"][i][
                "summary"
            ] = f"<p>{self.get_prompt(
                job_histories[i].split("/")[-1]
            ).response}</p>"

        for i in range(len(skills_types)):
            resume["sections"]["skills"]["items"][i]["keywords"] = [
                k.strip()
                for k in (self.get_prompt(skills_types[i]).response or "").split(",")
            ]

        rs = ResumeService(
            username=os.getenv("RESUME_USERNAME"),
            password=os.getenv("RESUME_PASSWORD"),
        )

        if self.resume_id is None:
            self.resume_id = rs.create()

        rs.update(self.resume_id, resume)
        self.resume_url = rs.get_pdf_url(self.resume_id)
        print(self.resume_id, self.resume_url)
        self.save()

        return f"{self.company} - {self.resume_url}"

    def delete(self):
        rs = ResumeService(
            username=os.getenv("RESUME_USERNAME"),
            password=os.getenv("RESUME_PASSWORD"),
        )
        rs.delete(self.resume_id)
        return super().delete()


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

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        print(self.application)
        return f"{self.application.company} -> {self.name}"

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
        default=URLStatus.objects.get(name="todo"),
    )

    def __str__(self):
        return f"{self.status}-{self.url}"
