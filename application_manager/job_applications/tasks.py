import logging

from django.utils import timezone
from subprocess import call
from celery import shared_task
from django.apps import apps
import os
import requests
from pyppeteer import connect
from datetime import timedelta
from django.conf import settings


logger = logging.getLogger(__name__)


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


def dispatch_generate_prompts(application_id: int) -> None:
    """Best-effort dispatch of the prompt pipeline.

    Called from `Application.save()` on commit, so a broker that is down must
    not break the admin save.
    """
    try:
        generate_prompts.delay(application_id)
    except Exception:
        logger.warning(
            "could not dispatch generate_prompts for application %s",
            application_id,
            exc_info=True,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def generate_prompts(self, application_id: int, force: bool = False):
    """Run the prompt pipeline for one application, synchronously."""
    from . import ai

    try:
        deps = ai.collect_inputs(application_id)
        prompts = ai.prepare_prompts(application_id)
        ai.run_pipeline(deps, prompts, force=force)
        ai.persist_results(prompts)
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def backup_to_file():
    call(
        ["make", "backup"],
        cwd=os.path.join(
            apps.get_app_config("job_applications").path,
            "../",
        ),
    )


@shared_task
def requests_check_urls():
    from .models import Application, ApplicationStatus

    deleted_status = ApplicationStatus.objects.get(name__exact="deleted")
    print(f"{deleted_status=}")
    applications = Application.objects.exclude(
        status__exact=deleted_status,
        job_url__isnull=True,
        last_scanned_requests__lt=timezone.now()
        + timedelta(**settings.TASK_SCAN["requests_scan_date_offset"]),
    ).order_by("-last_scanned_requests")[:20]
    print(f"{applications=}")
    for app in applications:
        request_result = requests.get(app.job_url)
        print(f"{request_result=}")
        if request_result.status_code != 200:
            app.status = deleted_status
        app.last_scanned_requests = timezone.now()
        app.save()
