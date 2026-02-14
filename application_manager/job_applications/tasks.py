from django.utils import timezone
from subprocess import call
from celery import shared_task
from django.apps import apps
from .services import FileService
import os
import requests
from pyppeteer import connect


# @shared_task
# def fill_in_prompts():
#     from .models import Application, ApplicationStatus

#     app = Application.objects.filter(
#         status__exact=ApplicationStatus.objects.get(name__exact="todo").name
#     ).last()
#     for prompt in app.prompts.all():
#         if prompt.response is not None:
#             print(prompt.description)
#     app.status = ApplicationStatus.objects.get(name__exact="ready")
#     app.save()


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


@shared_task
def requests_check_urls():
    from .models import Application, ApplicationStatus

    deleted_status = ApplicationStatus.objects.get(name__exact="deleted")
    applications = Application.objects.exclude(
        status__exact=deleted_status.name,
        job_url__isnull=True,
        job_url__icontains="linkedin",
    ).order_by("-last_scanned_requests")[:20]
    for app in applications:
        result = requests.get(app.job_url)
        print(result)
        if result.status_code != 200:
            app.status = deleted_status
        app.last_scanned_requests = timezone.now()
        app.save()


@shared_task
async def browserless_check_urls():
    from .models import Application, ApplicationStatus

    browser = await connect(
        {
            "browserWSEndpoint": f"{os.getenv('CHROME_URL')}/?token={os.getenv('CHROME_TOKEN')}"
        }
    )
    deleted_status = ApplicationStatus.objects.get(name__exact="deleted")
    page = await browser.newPage()

    applications = Application.objects.exclude(status__exact=deleted_status.name)
    for app in applications:
        await page.goto(app.job_url)
        print(await page.content())

    await browser.close()
