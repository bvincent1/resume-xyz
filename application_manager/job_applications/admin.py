from django.contrib import admin

from .models import ApplicationStatus, Application, Prompt


class ApplicationAdmin(admin.ModelAdmin):
    model = Application
    readonly_fields = ("prompts",)

    fieldsets = [
        (
            None,
            {
                "fields": (
                    "company",
                    "title",
                    "job_url",
                    "description",
                    "status",
                    "resume_url",
                ),
            },
        ),
        (
            "Additional information",
            {
                "classes": ["collapse"],
                "fields": ["prompts"],
            },
        ),
    ]

    def prompts(self, app):
        return "\n".join(app.list_prompts())


admin.site.register(ApplicationStatus)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(Prompt)
# Register your models here.
