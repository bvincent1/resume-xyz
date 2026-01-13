from subprocess import call
from celery import shared_task
from django.apps import apps
from .services import FileService
import os


@shared_task
def fill_in_prompts():
    from .models import Application, ApplicationStatus

    app = Application.objects.filter(
        status__exact=ApplicationStatus.objects.get(name__exact="todo").name
    ).last()
    for prompt in app.prompts.all():
        if prompt.response is not None:
            print(prompt.description)
    app.status = ApplicationStatus.objects.get(name__exact="ready")
    app.save()


@shared_task
def backup_to_file():
    call(
        ["make", "backup"],
        cwd=os.path.join(
            apps.get_app_config("job_applications").path,
            "../",
        ),
    )
    s3 = FileService()
    s3.upload_file(
        os.path.join(
            apps.get_app_config("job_applications").path,
            "../backup.tar",
        )
    )
