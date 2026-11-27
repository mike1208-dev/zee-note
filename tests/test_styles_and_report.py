import json
from types import SimpleNamespace

import pytest

from checker import local_model
from checker.basic_checks import CHECKS
from checker.loader import read_document
from checker.report import run_checks, summary
from checker.result import FAIL, PASS, SKIP, WARN
from checker.styles import Style, load_styles

DAILY_REPORT = """# Daily report
## Yesterday
- Fixed the login bug on the settings page.
## Today
- Write tests for the login flow.
## Blockers
- None.
"""


class FakeClient:
    """Stands in for groq.Groq so tests don't need an API key or network."""

    def __init__(self, content=None, error=None):
        self.content, self.error = content, error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture(scope="module")
def styles():
    return load_styles()


def test_every_rule_file_loads_and_uses_known_checks(styles):
    assert {"daily_report", "issue_pr", "work_plan"} <= set(styles)
    for style in styles.values():
        assert style.rules, f"{style.id} has no rules"
        for rule in style.rules:
            assert "id" in rule, f"{style.id}: rule without id"
            assert rule.get("check") in {*CHECKS, "llm"}, f"{style.id}/{rule['id']}: unknown check"
            if rule["check"] == "llm":
                assert rule.get("question"), f"{style.id}/{rule['id']}: llm rule needs a question"


def test_run_checks_without_ai(styles):
    results = run_checks(DAILY_REPORT, styles["daily_report"], use_llm=False)
    by_id = {r.rule_id: r for r in results}
    assert by_id["has_sections"].status == PASS
    assert by_id["concrete_tasks"].status == SKIP
    assert summary(results).endswith("(5 skipped)")


@pytest.mark.parametrize(
    "client, expected",
    [
        (FakeClient(json.dumps({"verdict": "pass", "reason": "ok", "quote": ""})), PASS),
        (FakeClient(json.dumps({"verdict": "fail", "reason": "vague", "quote": "worked on stuff"})), FAIL),
        (FakeClient(json.dumps({"verdict": "unsure", "reason": "?", "quote": ""})), WARN),
        (FakeClient('{"verdict": "fail", "reason": "x", "quote": "two\nlines"}'), FAIL),  # a line break in a quote
        (FakeClient('{"verdict": "pass", "reason": "a\x01b", "quote": ""}'), WARN),  # other control characters
        (FakeClient("not json"), WARN),
        (FakeClient("[]"), WARN),
        (FakeClient("null"), WARN),
        (FakeClient(None), WARN),
        (FakeClient(error=ConnectionError("Groq is unreachable")), SKIP),
    ],
)
def test_llm_rule_results(client, expected):
    style = Style(id="t", name="Test", rules=[{"id": "clear", "check": "llm", "question": "Is it clear?"}])
    [result] = run_checks("Some text.", style, client=client)
    assert result.status == expected


@pytest.mark.parametrize(
    "reason, quote, expected",
    [
        ("It uses the abbreviation 'Workflow' without explanation.", "", PASS),
        ("It uses the abbreviation FEAT without explanation.", "", PASS),
        ("Unexplained terms 'APIs' and 'C/C++'.", "", PASS),
        ("It uses an unexplained term.", "- API", PASS),
        ("It uses the abbreviation IPA without explanation.", "IPA", FAIL),
        ("Unexplained terms 'API' and 'IPA'.", "", FAIL),
        ("It uses an internal name without explanation.", "Update the Flux API", FAIL),  # Flux is unknown
        ("It uses an internal name without explanation.", "", FAIL),  # names nothing
        ("The report doesn't explain the term 'API'.", "", PASS),  # an apostrophe isn't a quote mark
        ("It uses Flux with the API without explanation.", "Flux", FAIL),
        ("The terms 'API' and VPC are not explained.", "", FAIL),
        ("Internal service Falcon is named in a FEAT without explanation.", "", FAIL),
        ("Terms such as 'API' and kubelet are not explained.", "", FAIL),
        ("It uses the term 'API' without explanation.", "Update the Flux API", FAIL),
        ("It uses the term 'API' without explanation.", "Update the API (#42)", PASS),
        ("It uses an internal name in the workflow without explanation.", "", FAIL),  # workflow is only part of the sentence
        ("It uses the term 'API' without explanation.", "Update the kubelet config via the API", FAIL),
        ("The report uses API without explaining the new term.", "Update the kubelet config via the API", FAIL),
        ("It uses the term 'API' without explanation.", "Flux API update", FAIL),
        ("It uses the term 'API' without explanation.", "- Fixed the API and updated the workflow", PASS),
        ("", "Flux", FAIL),
        ("", "", FAIL),
    ],
)
def test_known_terms_are_not_a_problem(reason, quote, expected):
    rule = {"id": "terms", "check": "llm", "question": "Explained?", "known_terms": ["API", "FEAT", "workflow", "C/C++"]}
    client = FakeClient(json.dumps({"verdict": "fail", "reason": reason, "quote": quote}))
    [result] = run_checks("Some text.", Style(id="t", name="Test", rules=[rule]), client=client)
    assert result.status == expected


def test_known_terms_can_be_numbers():
    rule = {"id": "terms", "check": "llm", "question": "Explained?", "known_terms": [404, "API"]}
    client = FakeClient(json.dumps({"verdict": "fail", "reason": "It uses the term 'API' without explanation.", "quote": ""}))
    [result] = run_checks("Some text.", Style(id="t", name="Test", rules=[rule]), client=client)
    assert result.status == PASS


def test_a_fail_is_kept_without_known_terms():
    client = FakeClient(json.dumps({"verdict": "fail", "reason": "It uses 'API'.", "quote": ""}))
    [result] = run_checks("Some text.", Style(id="t", name="Test", rules=[{"id": "a", "check": "llm", "question": "?"}]), client=client)
    assert result.status == FAIL


def test_a_document_with_a_secret_is_not_sent_to_the_ai_service(styles):
    client = FakeClient(json.dumps({"verdict": "pass", "reason": "", "quote": ""}))
    text = "## Summary\npassword: hunter22"
    results = {r.rule_id: r for r in run_checks(text, styles["issue_pr"], client=client)}
    assert results["no_secrets"].status == WARN and results["explains_why"].status == SKIP
    assert not client.calls

    run_checks(text, styles["issue_pr"], model=local_model.MODEL_ID, client=client)  # stays in the app
    assert len(client.calls) == 1


def test_unknown_check_is_skipped_not_crashed():
    style = Style(id="t", name="Test", rules=[{"id": "x", "check": "spellcheck"}])
    [result] = run_checks("text", style, use_llm=False)
    assert result.status == SKIP


def test_read_markdown_and_unsupported():
    assert read_document("a.md", "﻿# Title".encode("utf-8")) == "# Title"
    with pytest.raises(ValueError):
        read_document("a.xlsx", b"")


def test_read_docx_keeps_headings():
    docx = pytest.importorskip("docx")
    import io

    document = docx.Document()
    document.add_heading("Done", level=2)
    document.add_paragraph("Fixed the login bug.")
    buffer = io.BytesIO()
    document.save(buffer)
    assert read_document("a.docx", buffer.getvalue()) == "## Done\nFixed the login bug."


def test_llm_check_asks_groq_for_json():
    client = FakeClient(json.dumps({"verdict": "pass", "reason": "ok", "quote": ""}))
    style = Style(id="t", name="Test", rules=[{"id": "clear", "check": "llm", "question": "Is it clear?"}])
    run_checks("Some text.", style, model="m", client=client)
    assert client.calls[0]["model"] == "m"
    assert client.calls[0]["response_format"] == {"type": "json_object"}


def test_missing_groq_package_or_key_is_skipped(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    style = Style(id="t", name="Test", rules=[{"id": "clear", "check": "llm", "question": "Is it clear?"}])
    [result] = run_checks("Some text.", style)
    assert result.status == SKIP


def test_errors_of_the_ai_service_are_not_shown():
    class Client:
        def __init__(self, text, status):
            self.error = ConnectionError(text)
            self.error.status_code = status
            self.chat = self.completions = self

        def create(self, **_):
            raise self.error

    rule = {"id": "r", "title": "R", "check": "llm", "question": "ok?"}
    for text, status, expected in (
        ("Rate limit reached in organization org_123", 429, "limit is reached"),
        ("tokens per day (TPD) in organization org_123", 429, "Today's free limit"),
        ("org_123", 500, "didn't answer"),
    ):
        message = run_checks("text", Style(id="s", name="S", rules=[rule]), client=Client(text, status))[0].message
        assert expected in message and "org_123" not in message
