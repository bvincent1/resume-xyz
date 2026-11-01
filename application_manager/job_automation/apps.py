from django.apps import AppConfig


class JobAutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "job_automation"

    def ready(self):
        from . import schema  # noqa: F401  registers the auth scheme
