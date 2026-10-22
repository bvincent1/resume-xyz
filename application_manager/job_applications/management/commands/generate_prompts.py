from django.core.management.base import BaseCommand
from job_applications.models import Application
from job_applications.tasks import generate_prompts


class Command(BaseCommand):
    help = "Generate prompts for applications"

    def handle(self, *args, **kwargs):
        for application in Application.objects.filter(status__name="todo"):
            generate_prompts.delay(application.pk, force=True)

        self.stdout.write(self.style.SUCCESS("Successfully regenerated prompts"))
