import requests
import boto3
from botocore.config import Config
import os
from django.conf import settings
from jinja2 import Environment, FileSystemLoader, Template

file_env = Environment(
    loader=FileSystemLoader(str(settings.BASE_DIR / "application_manager"))
)

import httpx2
from django.conf import settings
from jinja2 import Environment, FileSystemLoader
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


env = Environment(loader=FileSystemLoader(str(settings.BASE_DIR / "application_manager")))


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


def generate_pdf(resume, host=None):
    """Render a JSON Resume object to a PDF via the json-resume-api service.

    POSTs the resume to the service and returns the absolute URL of the
    generated PDF.
    """
    host = (host or os.getenv("RESUME_SERVICE_HOST", "")).rstrip("/")

    r = requests.post(f"{host}/resume", json=resume)
    r.raise_for_status()

    return f"{host}{r.json()['path']}"


def read_supporting_document(path):
    """Read a supporting document from the local filesystem.

    ``path`` mirrors the S3 key previously used and is relative to the Django
    project directory, e.g. ``supporting_documents/histories/bvs.md``.
    """
    return (settings.BASE_DIR / "application_manager" / path).read_text(
        encoding="utf-8"
    )


def render_template(path="", **context):
    """Render jinja templated file. Default applies "env" vars.

    Args:
        path (str, optional): Path to templating file. Defaults to "".
        render_args (dict, optional): kwargs to template with, Default includes `{"env": ...}`. Defaults to {}.

    Returns:
        str: Templated file str
    """
    return file_env.get_template(path).render(**(context | {"env": os.environ}))


def render_string(source="", render_args={}):
    """Renders Jinja templating over provided string. Default applies "env" vars.

    Args:
        source (str, optional): Source string to template. Defaults to "".
        render_args (dict, optional): kwargs to template with, Default includes `{"env": ...}`. Defaults to {}.

    Returns:
        str: Templated string
    """
    return Template(source=source).render(**(render_args | {"env": os.environ}))

