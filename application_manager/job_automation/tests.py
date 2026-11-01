import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from application_manager.celery import app as celery_app
from job_applications import ai
from job_applications.models import (
    Application,
    PromptProvider,
    read_supporting_document,
)

from .models import JobURL, URLStatus
from .tasks import JobScanError, scan_job_url_task


RESEARCH_MARKER = "Job automation research marker"
SCAN_RESULT = {
    "title": "Senior Engineer",
    "company": "Acme",
    "description": "Build deterministic things.",
}


class _FakeSearch:
    def query(self, query, purpose=None):
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    url="https://acme.test/engineering",
                    title="Acme engineering",
                    snippet="Acme builds widgets.",
                )
            ]
        )


class _FakeFetch:
    def get_contents(self, urls, format=None, purpose=None):
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    url=url,
                    title="Acme engineering",
                    text=f"{RESEARCH_MARKER}: Acme builds widgets.",
                )
                for url in urls
            ],
            errors=[],
        )


class _FakeAgentRun:
    def run(self, *, goal, url, output_schema=None):
        if self.status == "COMPLETED":
            return SimpleNamespace(
                status=self.status,
                result=self.result,
                error=None,
                num_of_steps=1,
            )
        return SimpleNamespace(
            status=self.status,
            result=None,
            error=SimpleNamespace(message="could not scan the posting"),
            num_of_steps=1,
        )


class _FakeTinyFish:
    status = "COMPLETED"
    result = SCAN_RESULT

    def __init__(self, **kwargs):
        self.agent = _FakeAgentRun()
        self.agent.status = self.__class__.status
        self.agent.result = self.__class__.result
        self.search = _FakeSearch()
        self.fetch = _FakeFetch()


class _FailingTinyFish(_FakeTinyFish):
    status = "FAILED"


class _FakeTuningAgent:
    def __init__(self, output):
        self.output = output

    def run_sync(self, prompt, deps=None):
        if RESEARCH_MARKER not in (deps.company_research or ""):
            raise AssertionError("company research missing from pipeline deps")
        return SimpleNamespace(output=self.output)


@override_settings(JOB_AUTOMATION_API_KEY="test-key")
class JobAutomationIntegrationTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Celery reads its config once at startup, so override_settings cannot
        # switch it to eager mode; do it on the app and use the memory broker.
        cls._celery_settings = {
            "task_always_eager": celery_app.conf.task_always_eager,
            "task_eager_propagates": celery_app.conf.task_eager_propagates,
            "broker_url": celery_app.conf.broker_url,
        }
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            broker_url="memory://",
        )

    @classmethod
    def tearDownClass(cls):
        celery_app.conf.update(**cls._celery_settings)
        super().tearDownClass()

    def setUp(self):
        self.provider = PromptProvider.objects.create(
            name="acme-provider",
            model="test-model",
            url="https://example.com/v1",
            env_key="TEST_PROVIDER_KEY",
        )
        base = json.loads(
            read_supporting_document("supporting_documents/json-resume.json")
        )
        base["basics"]["summary"] = "Job automation summary"
        self.resume = ai.ResumeDocument.model_validate(base)
        self.client = APIClient()

    def _post(self, payload, key="test-key"):
        extra = {"HTTP_X_API_KEY": key} if key is not None else {}
        return self.client.post(
            "/api/job-automation/job-urls/",
            payload,
            format="json",
            **extra,
        )

    def _env(self):
        return patch.dict(
            os.environ,
            {
                "TINYFISH_API_KEY": "test",
                "TEST_PROVIDER_KEY": "secret",
            },
        )

    def test_post_scans_posting_and_fills_application(self):
        with self._env():
            with patch("tinyfish.TinyFish", _FakeTinyFish):
                with patch(
                    "job_applications.ai.build_agent",
                    return_value=_FakeTuningAgent(self.resume),
                ):
                    response = self._post({"url": "https://jobs.test/123"})

        self.assertEqual(response.status_code, 201)

        job_url = JobURL.objects.get()
        self.assertEqual(job_url.status.name, "done")
        self.assertIsNone(job_url.error)

        application = job_url.application
        self.assertIsNotNone(application)
        self.assertEqual(application.title, "Senior Engineer")
        self.assertEqual(application.company, "Acme")
        self.assertEqual(application.description, "Build deterministic things.")
        self.assertEqual(application.job_url, "https://jobs.test/123")
        self.assertEqual(application.provider, self.provider)

        self.assertIn(RESEARCH_MARKER, application.company_research)
        self.assertIsNotNone(application.company_researched_at)
        self.assertIsNotNone(application.prompt.response)
        self.assertIsNone(application.prompt.error)

    def test_requires_api_key(self):
        for key in (None, "wrong-key"):
            with self.subTest(key=key):
                response = self._post({"url": "https://jobs.test/123"}, key=key)
                self.assertEqual(response.status_code, 401)
                self.assertFalse(JobURL.objects.exists())

    def test_scan_failure_is_recorded(self):
        job_url = JobURL.objects.create(
            url="https://jobs.test/123",
            status=URLStatus.objects.create(name="todo"),
        )

        with self._env():
            with patch("tinyfish.TinyFish", _FailingTinyFish):
                with self.assertRaises(JobScanError):
                    scan_job_url_task(job_url.pk)

        job_url.refresh_from_db()
        self.assertEqual(job_url.status.name, "failed")
        self.assertIn("could not scan", job_url.error)
        self.assertFalse(Application.objects.exists())
