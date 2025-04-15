from django.core.management.base import BaseCommand
from pprint import pprint
from job_applications.models import Application


class Command(BaseCommand):
    help = "Generate pdfs for applications"

    def handle(self, *args, **kwargs):
        [a.generate_all_prompts() for a in Application.objects.filter(status__name="todo")]

        self.stdout.write(self.style.SUCCESS("Successfully regenerated prompts"))
