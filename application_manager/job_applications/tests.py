import copy
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from jsonschema import ValidationError

from . import ai
from .models import Application, PromptProvider, read_supporting_document


def base_resume():
    return json.loads(
        read_supporting_document("supporting_documents/json-resume.json")
    )


class ResumeDocumentTests(SimpleTestCase):
    def test_round_trip(self):
        base = base_resume()

        document = ai.ResumeDocument.model_validate(base)
        dumped = document.model_dump(
            by_alias=True, mode="json", exclude_none=True
        )

        self.assertEqual(dumped["$schema"], base["$schema"])
        self.assertEqual(dumped["work"][0]["name"], "Fortra")

    def test_validate_base_resume(self):
        ai.validate_resume(base_resume())

    def test_validate_rejects_unknown_root_keys(self):
        blob = base_resume()
        blob["unexpected"] = True

        with self.assertRaises(ValidationError):
            ai.validate_resume(blob)


class MergeResumeTests(SimpleTestCase):
    def test_preserves_omitted_sections_and_entries(self):
        base = {
            "basics": {"name": "Ben", "summary": "old"},
            "work": [
                {
                    "name": "BVS",
                    "position": "Solutions Engineer",
                    "summary": "old",
                }
            ],
            "skills": [{"name": "Frontend", "keywords": ["React"]}],
            "education": [{"institution": "UAlberta"}],
        }
        patch = {
            "basics": {"summary": "new"},
            "work": [{"name": "BVS", "summary": "new"}],
            "skills": [{"name": "Frontend", "keywords": ["Vue"]}],
        }

        merged = ai.merge_resume(base, patch)

        self.assertEqual(merged["basics"]["name"], "Ben")
        self.assertEqual(merged["basics"]["summary"], "new")
        self.assertEqual(merged["work"][0]["position"], "Solutions Engineer")
        self.assertEqual(merged["work"][0]["summary"], "new")
        self.assertEqual(merged["skills"][0]["keywords"], ["Vue"])
        self.assertEqual(merged["education"], [{"institution": "UAlberta"}])


class ResearchCompanyTests(SimpleTestCase):
    def test_missing_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            brief = ai.build_company_brief("Acme")

        self.assertEqual(brief, ai.RESEARCH_UNAVAILABLE_NO_KEY)

    def test_request_error_is_non_fatal(self):
        with patch.dict(os.environ, {"TINYFISH_API_KEY": "test"}):
            with patch.object(
                ai, "search_company", side_effect=RuntimeError("boom")
            ):
                brief = ai.build_company_brief("Acme")

        self.assertIn("Company research unavailable: boom.", brief)

    def test_cached_brief_skips_network(self):
        deps = ai.PipelineDeps(
            job_description="",
            company="Acme",
            company_research="cached brief",
        )
        ctx = SimpleNamespace(deps=deps)

        with patch.object(ai, "build_company_brief") as build:
            self.assertEqual(ai.research_company(ctx), "cached brief")

        build.assert_not_called()


class ProviderAuthTests(SimpleTestCase):
    def provider(self, env_key="TEST_PROVIDER_KEY"):
        return PromptProvider(
            name="test-model",
            url="https://example.com/v1",
            env_key=env_key,
        )

    def test_env_key_resolves_api_key(self):
        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "secret"}):
            self.assertEqual(ai._api_key_for(self.provider()), "secret")

    def test_missing_env_key_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            ai._api_key_for(self.provider(env_key=""))

    def test_unset_env_var_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ImproperlyConfigured):
                ai._api_key_for(self.provider())

    def test_build_agent_creates_its_own_openai_client(self):
        application = SimpleNamespace(provider=self.provider())

        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "secret"}):
            with patch.object(ai, "AsyncOpenAI") as openai_client:
                with patch.object(ai, "OpenAIChatModel"):
                    with patch.object(ai, "OpenAIProvider"):
                        with patch.object(ai, "Agent") as agent:
                            ai.build_agent(application)

        openai_client.assert_called_once_with(
            base_url="https://example.com/v1",
            api_key="secret",
            timeout=60,
        )
        agent.return_value.tool.assert_called()


class BuildPdfTests(SimpleTestCase):
    def _application(self, tuning):
        return Application(pk=1, company="Acme", tuning=tuning, status_id=1)

    def test_applies_tracking_payload_and_certificate_toggles(self):
        tuning = base_resume()
        tuning["basics"]["summary"] = "Tuned summary"
        tuning["payload"] = "python, django"
        application = self._application(tuning)
        application.include_project_management = True
        application.include_databricks = False

        with patch.object(Application, "save", return_value=None):
            with patch(
                "job_applications.models.generate_pdf",
                return_value="http://pdf",
            ) as generate:
                url = application.build_pdf()

        rendered = generate.call_args.args[0]

        self.assertEqual(url, "http://pdf")
        self.assertEqual(rendered["basics"]["summary"], "Tuned summary")
        self.assertEqual(
            rendered["basics"]["email"], "benjc.vincent+1@gmail.com"
        )
        self.assertIn("<p>python, django</p>", rendered["payload"])
        self.assertEqual(
            [cert["name"] for cert in rendered["certificates"]],
            ["Project Management"],
        )

    def test_invalid_blob_falls_back_to_base_resume(self):
        tuning = base_resume()
        tuning["basics"]["summary"] = "Tuned summary"
        tuning["unexpected"] = True
        application = self._application(tuning)

        with patch.object(Application, "save", return_value=None):
            with patch(
                "job_applications.models.generate_pdf",
                return_value="http://pdf",
            ) as generate:
                application.build_pdf()

        rendered = generate.call_args.args[0]

        self.assertEqual(rendered["basics"]["summary"], base_resume()["basics"]["summary"])


class RunTuningTests(TestCase):
    def setUp(self):
        self.provider = PromptProvider.objects.create(
            name="test-provider",
            url="https://example.com/v1",
            env_key="TEST_PROVIDER_KEY",
        )
        self.application = Application.objects.create(
            title="Engineer",
            description="Build things",
            company="Acme",
            provider=self.provider,
        )

    def test_run_tuning_persists_merged_blob_and_prompt(self):
        base = base_resume()
        output = ai.ResumeDocument.model_validate(
            {**base, "basics": {**base["basics"], "summary": "Tuned summary"}}
        )
        fake_agent = SimpleNamespace(
            run_sync=lambda *args, **kwargs: SimpleNamespace(output=output)
        )

        with patch.object(ai, "build_agent", return_value=fake_agent):
            with patch.object(
                ai, "ensure_company_research", return_value="company brief"
            ):
                with patch.object(
                    ai,
                    "collect_inputs",
                    return_value=ai.PipelineDeps(
                        job_description="Build things", company="Acme"
                    ),
                ):
                    result = ai.run_tuning(self.application.pk, force=True)

        self.application.refresh_from_db()
        self.assertEqual(result.basics.summary, "Tuned summary")
        self.assertEqual(
            self.application.tuning["basics"]["summary"], "Tuned summary"
        )
        self.assertEqual(
            self.application.tuning["work"][0]["position"], "Senior Software Engineer"
        )
        self.assertIsNotNone(self.application.prompt.response)
        self.assertIsNone(self.application.prompt.error)

    def test_run_tuning_records_errors(self):
        with patch.object(ai, "build_agent", side_effect=RuntimeError("boom")):
            with patch.object(
                ai, "ensure_company_research", return_value="company brief"
            ):
                with patch.object(
                    ai,
                    "collect_inputs",
                    return_value=ai.PipelineDeps(
                        job_description="Build things", company="Acme"
                    ),
                ):
                    with self.assertRaises(RuntimeError):
                        ai.run_tuning(self.application.pk, force=True)

        self.application.refresh_from_db()
        self.assertIsNone(self.application.tuning)
        self.assertEqual(self.application.prompt.error, "boom")


class EnsureCompanyResearchTests(TestCase):
    def setUp(self):
        provider = PromptProvider.objects.create(
            name="test-provider",
            url="https://example.com/v1",
            env_key="TEST_PROVIDER_KEY",
        )
        self.application = Application.objects.create(
            title="Engineer",
            description="Build things",
            company="Acme",
            provider=provider,
            company_research="cached brief",
            company_researched_at=timezone.now(),
        )

    def test_fresh_cache_skips_crawl(self):
        with patch.object(ai, "build_company_brief") as build:
            brief = ai.ensure_company_research(self.application)

        self.assertEqual(brief, "cached brief")
        build.assert_not_called()

    def test_stale_cache_crawls_and_persists(self):
        self.application.company_researched_at = timezone.now() - timedelta(days=8)
        self.application.save()

        with patch.object(
            ai, "build_company_brief", return_value="fresh brief"
        ) as build:
            brief = ai.ensure_company_research(self.application)

        self.assertEqual(brief, "fresh brief")
        build.assert_called_once_with("Acme")
        self.application.refresh_from_db()
        self.assertEqual(self.application.company_research, "fresh brief")
        self.assertIsNotNone(self.application.company_researched_at)

    def test_force_ignores_fresh_cache(self):
        with patch.object(
            ai, "build_company_brief", return_value="forced brief"
        ) as build:
            brief = ai.ensure_company_research(self.application, force=True)

        self.assertEqual(brief, "forced brief")
        build.assert_called_once_with("Acme")
