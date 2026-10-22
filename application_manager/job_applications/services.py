import requests
import boto3
from botocore.config import Config
import os

import httpx2
from django.conf import settings
from jinja2 import Environment, FileSystemLoader
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


env = Environment(loader=FileSystemLoader(str(settings.BASE_DIR / "application_manager")))


def render_template(template_name, **context) -> str:
    """Render a Jinja template from the project directory with the given context."""
    return env.get_template(template_name).render(**context)


def build_model(name, url, headers) -> Model:
    """Build a pydantic-ai Model from a provider's details.

    ``name`` is the model id sent to the API, ``url`` the OpenAI-compatible base
    url, ``headers`` the HTTP headers (including ``Authorization: Bearer <key>``).

    The client is async because pydantic-ai's provider layer is async even when
    the agent is driven with ``run_sync``. Build it once per provider and reuse
    it.
    """
    headers = dict(headers or {})
    api_key = headers.pop("Authorization", "").removeprefix("Bearer ").strip()
    client = httpx2.AsyncClient(base_url=url, headers=headers, timeout=60)
    return OpenAIChatModel(
        name,
        provider=OpenAIProvider(base_url=url, api_key=api_key, http_client=client),
    )


def render_pdf(resume, host=None):
    """Render a JSON Resume object to a PDF via the json-resume-api service.

    POSTs the resume to the service and returns the absolute URL of the
    generated PDF.
    """
    host = (host or os.getenv("RESUME_SERVICE_HOST", "")).rstrip("/")

    r = requests.post(f"{host}/resume", json=resume)
    r.raise_for_status()

    return f"{host}{r.json()['path']}"


class FileService:
    def __init__(self, **kwargs):
        self.client = boto3.client(
            "s3",
            endpoint_url=kwargs.get("storage_host", os.getenv("STORAGE_HOST")),
            region_name=kwargs.get("storage_region", os.getenv("STORAGE_REGION")),
            aws_access_key_id=kwargs.get(
                "storage_access_key", os.getenv("STORAGE_ACCESS_KEY")
            ),
            aws_secret_access_key=kwargs.get(
                "storage_secret_key", os.getenv("STORAGE_SECRET_KEY")
            ),
            aws_session_token=None,
            config=Config(signature_version="s3v4"),
            verify=False,
        )
        self.bucket = kwargs.get("bucket", "default")

    def open(self, file_path):
        return (
            self.client.get_object(Bucket=self.bucket, Key=file_path)["Body"]
            .read()
            .decode("utf-8")
        )

    def upload_file(self, file_name, object_name=None):
        """Upload a file to an S3 bucket

        :param file_name: File to upload
        :param bucket: Bucket to upload to
        :param object_name: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """

        # If S3 object_name was not specified, use file_name
        if object_name is None:
            object_name = os.path.basename(file_name)

        # Upload the file
        return self.client.upload_file(file_name, self.bucket, object_name)
