import logging
import os

from celery import shared_task
from pydantic import BaseModel

from job_applications.models import Application, PromptProvider

from .models import JobURL, URLStatus


logger = logging.getLogger(__name__)


def _strip_title_keys(node):
    """Drop JSON Schema ``title`` annotations Pydantic injects.

    ``JobPosting.model_json_schema()`` adds ``"title": "<ClassName>"`` at the
    root and ``"title": "<FieldName>"`` on every property. TinyFish rejects
    the ``title`` keyword anywhere in ``output_schema``, so walk the generated
    schema and pop the keyword at every depth before sending it.
    """
    if isinstance(node, dict):
        node.pop("title", None)
        for value in node.values():
            _strip_title_keys(value)
    elif isinstance(node, list):
        for item in node:
            _strip_title_keys(item)


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
    # TinyFish rejects the JSON Schema `title` keyword at any depth; strip
    # the ones Pydantic annotates before sending.
    output_schema = JobPosting.model_json_schema()
    _strip_title_keys(output_schema)
    response = client.agent.run(
        goal=(
            "Extract the role title, the hiring company, and the full job "
            "description verbatim."
        ),
        url=url,
        output_schema=output_schema,
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


def dispatch_scan(job_url_id: int) -> None:
    """Best-effort dispatch of a URL scan.

    Called from `JobURL.save()` on commit, so a broker that is down must not
    break the admin save or the API request.
    """
    try:
        scan_job_url_task.delay(job_url_id)
    except Exception:
        logger.warning(
            "could not dispatch scan for job url %s",
            job_url_id,
            exc_info=True,
        )


@shared_task
def scan_job_url_task(job_url_id: int, force: bool = False):
    """Scan one JobURL and create or refresh the application it describes."""
    job_url = JobURL.objects.get(pk=job_url_id)
    if job_url.application_id and not force:
        return

    try:
        posting = scan_posting(job_url.url)
        provider = default_provider()
        logger.info("scanning %s with provider %s", job_url.url, provider.name)

        if job_url.application_id:
            application = job_url.application
            application.title = posting.title
            application.company = posting.company
            application.description = posting.description[:20_000]
            application.job_url = job_url.url
            application.provider = provider
            application.save()
        else:
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
