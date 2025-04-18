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


class PromptAdmin(admin.ModelAdmin):
    model = Prompt
    list_display = ("__str__", "get_trimmed_response")


admin.site.register(ApplicationStatus)
admin.site.register(Application, ApplicationAdmin)
admin.site.register(Prompt, PromptAdmin)
# Register your models here.
