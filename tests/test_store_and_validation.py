import json
from types import SimpleNamespace

import httpx
import pytest

from checker.basic_checks import must_contain, pattern
from checker.report import run_checks
from checker.result import FAIL, PASS, SKIP
from checker.rule_import import draft_style
from checker.store import StoreError, SupabaseStore, YamlStore, get_store
from checker.styles import Style, load_styles
from checker.validation import validate_style

STYLE_ROW = {
    "id": "daily_report",
    "name": "Daily report",
    "description": "",
    "detect": ["daily report"],
    "rules": [{"id": "no_secrets", "title": "No secrets", "check": "no_secrets"}],
    "updated_at": "2026-11-20T10:00:00+00:00",
    "updated_by": "Mike",
}


def make_store(handler, key="sb_secret_test"):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return SupabaseStore("https://example.supabase.co", key, transport=httpx.MockTransport(record)), requests


# --- Supabase store ---------------------------------------------------------------------------


def test_list_styles_reads_rows_into_styles():
    store, requests = make_store(lambda r: httpx.Response(200, json=[STYLE_ROW]))
    styles = store.list_styles()
    assert styles["daily_report"].name == "Daily report"
    assert styles["daily_report"].rules[0]["check"] == "no_secrets"
    assert requests[0].url.path == "/rest/v1/styles"
    assert requests[0].headers["apikey"] == "sb_secret_test"
    assert "authorization" not in requests[0].headers  # new secret keys must not be sent as a Bearer token


def test_legacy_jwt_key_is_also_sent_as_bearer():
    store, requests = make_store(lambda r: httpx.Response(200, json=[]), key="eyJhbGciOi.test")
    store.list_styles()
    assert requests[0].headers["authorization"] == "Bearer eyJhbGciOi.test"


def test_save_style_upserts_with_editor_name():
    store, requests = make_store(lambda r: httpx.Response(201))
    store.save_style(Style.from_dict(STYLE_ROW), editor="Dan")
    request = requests[0]
    assert request.method == "POST"
    assert "resolution=merge-duplicates" in request.headers["prefer"]
    body = json.loads(request.content)
    assert body["id"] == "daily_report" and body["updated_by"] == "Dan"


def test_delete_and_restore():
    store, requests = make_store(lambda r: httpx.Response(204))
    store.delete_style("daily_report")
    assert requests[0].method == "DELETE" and requests[0].url.params["id"] == "eq.daily_report"

    history_row = {**STYLE_ROW, "style_id": "daily_report", "history_id": 7, "action": "delete"}
    del history_row["id"]
    store.restore(history_row, editor="Mike")
    assert json.loads(requests[1].content)["id"] == "daily_report"


def test_errors_become_store_errors():
    store, _ = make_store(lambda r: httpx.Response(401, text="Invalid API key"))
    with pytest.raises(StoreError, match="401"):
        store.list_styles()

    def unreachable(request):
        raise httpx.ConnectError("no network")

    store, _ = make_store(unreachable)
    with pytest.raises(StoreError, match="Can't reach"):
        store.list_styles()


@pytest.mark.parametrize("response", [{"text": "<html>"}, {"json": {"message": "x"}}, {"json": [{"name": "no id"}]}, {}])
def test_unreadable_answers_become_store_errors(response):
    store, _ = make_store(lambda r: httpx.Response(200, **response))
    with pytest.raises(StoreError):
        store.list_styles()


def test_save_styles_is_one_request():
    store, requests = make_store(lambda r: httpx.Response(201))
    store.save_styles(list(load_styles().values()), editor="Dan")
    [request] = requests
    assert [row["id"] for row in json.loads(request.content)] == ["daily_report", "issue_pr", "work_plan"]


def test_get_store_falls_back_to_yaml_without_settings(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert isinstance(get_store(), YamlStore)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_secret_test")
    assert isinstance(get_store(), SupabaseStore)
    assert get_store() is get_store()


# --- Validation -------------------------------------------------------------------------------


def test_example_rule_files_are_valid():
    for style in load_styles().values():
        assert validate_style(style) == [], style.id


def test_validation_finds_problems():
    style = Style(
        id="Bad ID",
        name="",
        rules=[
            {"id": "a", "check": "llm"},
            {"id": "a", "check": "no_secrets"},
            {"id": "b", "check": "pattern", "pattern": "("},
            {"id": "c", "check": "spellcheck"},
            {"id": "d", "check": "word_count", "min": 100, "max": 10},
        ],
    )
    text = " ".join(validate_style(style))
    for expected in ["Style ID", "name is required", "'question' is required", "used twice", "not a valid regular expression", "unknown check type", "minimum is larger"]:
        assert expected in text


@pytest.mark.parametrize(
    "rule",
    [
        {"check": "word_count", "min": "50", "max": 100},
        {"check": "long_sentences", "max_words": None},
        {"check": "mention_at_top", "lines": 0},
        {"check": "required_sections", "sections": "Today"},
        {"check": "required_sections", "sections": [[]]},
        {"check": "must_contain", "phrases": [["a"]]},
        {"check": "pattern", "pattern": ["a"]},
        {"check": "llm", "question": 3},
        {"check": "no_secrets", "title": 5},
    ],
)
def test_validation_finds_wrong_types(rule):
    assert validate_style(Style(id="s", name="S", rules=[{"id": "a", **rule}]))


# --- New check types and safe running ---------------------------------------------------------


def test_must_contain():
    rule = {"id": "link", "phrases": ["Ticket:", "Reviewed by"]}
    assert must_contain("Ticket: ABC-1\nreviewed by Dan", rule).status == PASS
    result = must_contain("Ticket: ABC-1", rule)
    assert result.status == FAIL and "Reviewed by" in result.message


def test_pattern_must_match_and_must_not_match():
    ticket = {"id": "ticket", "pattern": r"[A-Z]+-\d+", "label": "ticket number"}
    assert pattern("Fixes ABC-123", ticket).status == PASS
    assert "No ticket number found" in pattern("Fixes the bug", ticket).message

    no_ip = {"id": "no_ip", "pattern": r"\b\d{1,3}(\.\d{1,3}){3}\b", "must": "not_match", "label": "an IP address"}
    result = pattern("Server\nat 10.0.0.12", no_ip)
    assert result.status == FAIL and result.where == "line 2"


def test_broken_rule_is_skipped_not_crashed():
    style = Style(id="t", name="Test", rules=[{"id": "x", "check": "pattern", "pattern": "("}])
    [result] = run_checks("text", style, use_llm=False)
    assert result.status == SKIP and "error" in result.message


# --- AI import --------------------------------------------------------------------------------


def fake_client(answer, calls):
    def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=json.dumps(answer))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.mark.parametrize("answer", [["a"], {"name": "N", "rules": "a"}, {"name": "N", "rules": ["a"]}, {"name": "N", "rules": [{"check": ["llm"]}]}])
def test_draft_style_rejects_a_wrong_answer(answer):
    with pytest.raises(ValueError, match="isn't a list of rules"):
        draft_style("text", model="m", client=fake_client(answer, []))


def test_draft_style_from_rule_document():
    answer = {
        "name": "Meeting notes",
        "description": "Decisions and action items.",
        "detect": "meeting notes, attendees",
        "rules": [{"id": "has_sections", "title": "Has sections", "check": "required_sections", "sections": ["Attendees"]}],
    }
    calls = []
    style = draft_style("Meeting notes must list attendees.", model="m", client=fake_client(answer, calls))
    assert style.id == "meeting_notes"
    assert style.detect == ["meeting notes", "attendees"]
    assert calls[0]["max_completion_tokens"] == 1000
    assert validate_style(style) == []
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_a_pattern_that_could_freeze_the_app_is_refused_and_never_run():
    rule = {"id": "words", "check": "pattern", "pattern": r"^(\w+\s?)+$", "must": "not_match"}
    assert any("too long to check" in problem for problem in validate_style(Style("t", "Test", [rule])))
    assert pattern("a" * 40 + "!", rule).status == SKIP  # an older saved rule isn't run either
    ip = {"id": "ip", "check": "pattern", "pattern": r"\b\d{1,3}(\.\d{1,3}){3}\b"}
    assert validate_style(Style("t", "Test", [ip])) == []  # a fixed count is fine


def test_must_and_ids_are_checked_exactly():
    odd = {"id": "x", "check": "pattern", "pattern": "x", "must": "never"}
    assert any("'must'" in problem for problem in validate_style(Style("t", "Test", [odd])))
    assert any("ID must" in problem for problem in validate_style(Style("t", "Test", [{"id": "abc\n", "check": "llm", "question": "q"}])))


def test_after_the_ai_limit_the_other_ai_rules_dont_ask_again():
    class Limited:
        calls = 0

        def create(self, **kwargs):
            Limited.calls += 1
            error = Exception("Rate limit reached")
            error.status_code = 429
            raise error

    client = SimpleNamespace(chat=SimpleNamespace(completions=Limited()))
    rules = [{"id": f"r{n}", "check": "llm", "question": "Is it fine?"} for n in range(4)]
    results = run_checks("Some report", Style("t", "Test", rules), client=client)
    assert Limited.calls == 1 and all(result.status == SKIP and "limit" in result.message for result in results)
