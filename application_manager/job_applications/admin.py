from django.contrib import admin
from unfold.admin import ModelAdmin
from django.core.validators import EMPTY_VALUES
from unfold.contrib.filters.admin import FieldTextFilter, RelatedCheckboxFilter

from .models import ApplicationStatus, Application, Prompt


class ApplicationAdmin(ModelAdmin):
    model = Application
    readonly_fields = ("prompts", "created", "updated")
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
            None,
            {
                "fields": (
                    "created",
                    "updated",
                )
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

    list_filter_submit = True  # Submit button at the bottom of the filter
    list_filter = [
        ("company", FieldTextFilter),
        ("title", FieldTextFilter),
        ("status", RelatedCheckboxFilter),
    ]

    actions = ["generate_pdfs", "regenerate_prompts"]

    def prompts(self, app):
        return "\n".join(app.list_prompts())

    @admin.action(description="Build pdfs")
    def generate_pdfs(self, request, queryset):
        for application in queryset:
            application.build_pdf()
        self.message_user(request, "PDFs generated successfully.")

    @admin.action(description="Regenerate prompts")
    def regenerate_prompts(self, request, queryset):
        for application in queryset:
            application.generate_all_prompts()
        self.message_user(request, "Prompts regenerated successfully.")


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


admin.site.register(ApplicationStatus, StatusAdmin)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(Prompt, PromptAdmin)
# Register your models here.
