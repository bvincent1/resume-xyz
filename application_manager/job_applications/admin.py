from json import loads
import pprint
from django.contrib import admin
from unfold.admin import ModelAdmin
from django.core.validators import EMPTY_VALUES
from unfold.contrib.filters.admin import FieldTextFilter, RelatedCheckboxFilter
from django.apps import apps
from subprocess import run, PIPE
from django.http import HttpRequest
from django.shortcuts import redirect
from unfold.decorators import action
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import ApplicationStatus, Application, JobURL, Prompt, URLStatus


class ApplicationAdmin(ModelAdmin):
    model = Application
    readonly_fields = (
        "id",
        "prompts",
        "created",
        "updated",
        "prompts_list",
    )
    fieldsets = [
        (
            None,
            {
                "fields": (
                    "id",
                    "company",
                    "title",
                    "job_url",
                    "description",
                    "status",
                    "resume_url",
                    "notes",
                    "prompts_list",
                ),
            },
        ),
        (
            None,
            {
                "fields": (
                    "created",
                    "updated",
                )
            },
        ),
    ]

    list_display = ("__str__", "created")
    list_filter_submit = True  # Submit button at the bottom of the filter
    list_filter = [
        ("company", FieldTextFilter),
        ("title", FieldTextFilter),
        ("status", RelatedCheckboxFilter),
    ]

    actions = ["generate_pdfs", "regenerate_prompts"]
    actions_detail = ["generate_pdf"]

    @action(
        description="Build PDF",
        url_path="generate-pdf-action",
        attrs={"target": "_blank"},
    )
    def generate_pdf(self, request: HttpRequest, object_id: int):
        app = Application.objects.get(pk=object_id)

        return redirect(app.build_pdf())

    @action(description="Build pdfs")
    def generate_pdfs(self, request, queryset):
        for application in queryset:
            application.build_pdf()
        self.message_user(request, "PDFs generated successfully.")

    @action(description="Regenerate prompts")
    def regenerate_prompts(self, request, queryset):
        for application in queryset:
            application.generate_all_prompts()
        self.message_user(request, "Prompts regenerated successfully.")

    def prompts_list(self, obj):
        links = [
            f'<li><a class="text-primary-600 dark:text-primary-500 underline" href="{reverse("admin:job_applications_prompt_change", args=(prompt.id,))}">{prompt.name}</a></li>'
            for prompt in obj.prompts.all()
        ]
        return mark_safe("<ul>" + "".join(links) + "</ul>")


class PromptAdmin(ModelAdmin):
    model = Prompt

    list_filter_submit = True  # Submit button at the bottom of the filter
    list_display = ("__str__", "get_trimmed_response")
    list_filter = [
        ("application__company", FieldTextFilter),
    ]

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "application",
                    "name",
                    "description",
                    "response",
                ),
            },
        ),
    ]


class StatusAdmin(ModelAdmin):
    pass


class URLStatusAdmin(ModelAdmin):
    pass


class JobURLAdmin(ModelAdmin):

    @action(description="Get job info")
    def get_job_info(self, request, queryset):
        urls_string = ",".join([url.url for url in queryset])
        result = run(
            ["node", "../scraper/src/getJobInfo.mjs", urls_string],
            cwd=apps.get_app_config("app_label").path,
            stderr=PIPE,
            stdout=PIPE,
            text=True,
        )
        if result.returncode == 0:
            job_infos = loads(result.stdout)
            pprint(job_infos)

        self.message_user(request, "Prompts regenerated successfully.")


# Register your models here.
admin.site.register(ApplicationStatus, StatusAdmin)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(Prompt, PromptAdmin)
admin.site.register(URLStatus, URLStatusAdmin)
admin.site.register(JobURL, JobURLAdmin)
