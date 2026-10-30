import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from job_applications.models import (
    Application,
    ApplicationStatus,
    PromptProvider,
)


class Command(BaseCommand):
    help = "Create the superuser, provider, and status used by the E2E tests."

    def handle(self, *args, **options):
        if os.getenv("E2E_STUBS") != "1":
            raise CommandError("seed_e2e only runs with E2E_STUBS=1")

        user_model = get_user_model()
        user, _created = user_model.objects.get_or_create(email="e2e@example.com")
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password("e2e-password")
        user.save()

        PromptProvider.objects.update_or_create(
            name="e2e-provider",
            defaults={
                "model": "e2e-model",
                "url": "http://127.0.0.1:9/v1",
                "env_key": "E2E_PROVIDER_KEY",
            },
        )
        ApplicationStatus.objects.get_or_create(name="todo")
        Application.objects.filter(company="Acme E2E").delete()

        self.stdout.write(self.style.SUCCESS("E2E fixtures ready."))
