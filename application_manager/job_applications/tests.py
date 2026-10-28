import copy
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
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
            headers={},
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
