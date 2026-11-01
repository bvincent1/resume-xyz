import logging
import os

from celery import shared_task
from pydantic import BaseModel

from job_applications.models import Application, PromptProvider

from .models import JobURL, URLStatus


logger = logging.getLogger(__name__)


class JobPosting(BaseModel):
    title: str
    company: str
    description: str


class JobScanError(Exception):
    """The posting could not be scanned or turned into an application."""


def scan_posting(url: str) -> JobPosting:
    """Scan a job posting URL with TinyFish and return its structured fields."""
    from tinyfish import TinyFish  # local import so tests can patch the SDK

    client = TinyFish(api_key=os.environ["TINYFISH_API_KEY"], timeout=120)
    response = client.agent.run(
        goal=(
            "Extract the role title, the hiring company, and the full job "
            "description verbatim."
        ),
        url=url,
        output_schema=JobPosting.model_json_schema(),
    )
    if response.status != "COMPLETED" or not response.result:
        raise JobScanError(str(response.error) if response.error else "scan failed")
    return JobPosting.model_validate(response.result)


def default_provider() -> PromptProvider:
    """Return the provider used for applications created from a scan."""
    provider = PromptProvider.objects.order_by("name").first()
    if provider is None:
        raise JobScanError("No PromptProvider configured.")
    return provider


@shared_task
def scan_job_url_task(job_url_id: int):
    """Scan one JobURL and create the application it describes."""
    job_url = JobURL.objects.get(pk=job_url_id)
    if job_url.application_id:
        return

    try:
        posting = scan_posting(job_url.url)
        provider = default_provider()
        logger.info("scanning %s with provider %s", job_url.url, provider.name)
        application = Application.objects.create(
            title=posting.title,
            company=posting.company,
            description=posting.description[:20_000],
            job_url=job_url.url,
            provider=provider,
        )
    except Exception as exc:
        job_url.status, _created = URLStatus.objects.get_or_create(name="failed")
        job_url.error = str(exc)
        job_url.save(update_fields=["status", "error"])
        raise

    job_url.application = application
    job_url.status, _created = URLStatus.objects.get_or_create(name="done")
    job_url.error = None
    job_url.save(update_fields=["application", "status", "error"])
