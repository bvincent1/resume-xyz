"""Replace external AI and research boundaries with deterministic fakes."""

import json
from types import SimpleNamespace

import tinyfish

from job_applications import ai
from job_applications.models import read_supporting_document

RESEARCH_MARKER = "E2E research marker"


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


class _FakeTinyFish:
    def __init__(self, **kwargs):
        self.search = _FakeSearch()
        self.fetch = _FakeFetch()


class _FakeAgent:
    def __init__(self, output):
        self.output = output

    def run_sync(self, prompt, deps=None):
        if RESEARCH_MARKER not in (deps.company_research or ""):
            raise AssertionError("company research missing from pipeline deps")
        return SimpleNamespace(output=self.output)


def install():
    tinyfish.TinyFish = _FakeTinyFish

    base = json.loads(read_supporting_document("supporting_documents/json-resume.json"))
    base["basics"]["summary"] = "E2E tuned summary"
    output = ai.ResumeDocument.model_validate(base)

    ai.build_agent = lambda application: _FakeAgent(output)
