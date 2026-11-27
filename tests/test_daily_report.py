import json
import sys

import pytest

from checker import llm_checks, local_model
from checker.basic_checks import mention_at_top, required_sections, working_hours
from checker.report import run_checks
from checker.result import FAIL, PASS, SKIP
from checker.styles import Style, load_styles

RULES = {rule["id"]: rule for rule in load_styles()["daily_report"].rules}

# As copied from Slack
SLACK_REPORT = """@Alex (Project Manager)
Good morning. Please confirm the daily report. Thank you.

• :white_check_mark: Weekend (6 hours).
◦ Made a plan to build the checker.
■ Defined the requirements.

• :dart: Today (7 hours).
◦ Prepare the training data.

• :construction: Blockers / :memo:Notes: .
◦ None.
"""

# As read through the Slack API, or written in Markdown
MARKDOWN_REPORT = """<@U0123|Sam> Please check.
- :white_check_mark: *Yesterday:* `5 hours`
    - Fixed the login bug (Merged)
- :dart: *Today*
    - Write tests - `2 hours`
- :construction: *Blockers /* :memo: *Notes:*
    - None
"""


@pytest.mark.parametrize("text", [SLACK_REPORT, MARKDOWN_REPORT, "@Sam\n## Yesterday (7h)\n- a\n## Today: 3 hrs\n- b\n## Notes\n- None"])
def test_good_reports_pass_the_code_rules(text):
    assert required_sections(text, RULES["has_sections"]).status == PASS
    assert mention_at_top(text, RULES["tags_reviewer"]).status == PASS
    assert working_hours(text, RULES["has_hours"]).status == PASS


def test_plan_example():
    text = "✅ Yesterday (7 hours)\n- Worked on the login page\n🎯 Today\n- Finish the login page\n🚧 Blockers\n- None"
    assert required_sections(text, RULES["has_sections"]).status == PASS
    assert mention_at_top(text, RULES["tags_reviewer"]).status == FAIL
    result = working_hours(text, RULES["has_hours"])
    assert result.status == FAIL
    assert "Today" in result.message and "Yesterday" not in result.message.split(". ")[0]


def test_missing_section():
    result = required_sections("✅ Yesterday\n- a\n🎯 Today\n- b", RULES["has_sections"])
    assert result.status == FAIL and "Blockers" in result.message


def test_plain_bullets_and_sentences_are_not_headings():
    text = "- Yesterday\n- Today\n- Blockers\nToday I fixed the notes."
    assert required_sections(text, RULES["has_sections"]).status == FAIL


def test_tag_must_be_at_the_top_and_not_an_email():
    assert mention_at_top("one\ntwo\nthree\n@Sam", RULES["tags_reviewer"]).status == FAIL
    assert mention_at_top("mike@example.com", RULES["tags_reviewer"]).status == FAIL
    assert mention_at_top("\n\nHi @Sam", RULES["tags_reviewer"]).status == PASS


def test_hours_inside_a_task_description_do_not_count():
    text = "Yesterday (7 hours)\n- a\nToday\n- Cut the build time from 2 hours to 5 minutes\nBlockers\n- Waiting - 3 hours"
    result = working_hours(text, RULES["has_hours"])
    assert result.status == FAIL and "Today" in result.message


@pytest.mark.parametrize(
    "line",
    ["Today - 7 hours", "Today 7h", "🎯 **Today** — 7h", "Today, Nov 20 (7 hours)", "⏰ Today (7h30m)", "👨‍💻 Today [7h]", ":+1: Today `7h`",
     ":100: Today: about 7 hours", "Today's (7h)", "1️⃣ Today Nov 20 7h", "Today / Plan (7 hours)", "Today: write tests (2 hours)"],
)
def test_headings_with_hours(line):
    text = f"Yesterday (7 hours)\n- a\n{line}\n- b\nBlockers - none"
    assert required_sections(text, RULES["has_sections"]).status == PASS
    assert working_hours(text, RULES["has_hours"]).status == PASS


@pytest.mark.parametrize("line", ["Today, I fixed it", "Today 2 hours were lost", "Today's bug was hard", "today-only flag", "Today 5 bugs"])
def test_sentences_that_start_with_a_section_name_are_not_headings(line):
    assert required_sections(line, {"id": "x", "sections": ["Today"]}).status == FAIL


@pytest.mark.parametrize(
    "line, expected",
    [
        ("- x (~2 hours)", PASS),
        ("- x (Merged, 3 hours)", PASS),
        ("- x - 2 hours (in review)", PASS),
        ("- x (2-3 hours)", PASS),
        ("- fix the retry (30 min timeout) bug", FAIL),
        ("Tomorrow (8 hours)\n- y (3 hours)", FAIL),
        ("## Ideas\n- y (3 hours)", FAIL),
        ("### Project A\n- y (3 hours)", PASS),
    ],
)
def test_hours_in_task_lines(line, expected):
    text = f"## Yesterday (7 hours)\n- a\n## Today\n{line}\n## Blockers\n- None"
    assert working_hours(text, RULES["has_hours"]).status == expected


def test_a_timeout_in_a_heading_line_is_not_working_time():
    assert working_hours("Yesterday (7h)\nToday: fix the 5 minute timeout", RULES["has_hours"]).status == FAIL


@pytest.mark.parametrize("name", ["🎯 Goals", "Tasks (this week)", "CI/CD", "Risks:"])
def test_section_names_with_emoji_brackets_or_slashes(name):
    assert required_sections(f"## {name}", {"id": "x", "sections": [name]}).status == PASS
    assert required_sections("## Tasks (next week)", {"id": "x", "sections": [name]}).status == FAIL


# --- Local model ------------------------------------------------------------------------------


class FakeLlama:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        content = json.dumps({"verdict": "fail", "reason": "Vague.", "quote": "Worked on it"})
        return {"choices": [{"message": {"content": content}}]}


LLM_STYLE = Style(id="t", name="Test", rules=[{"id": "clear", "check": "llm", "question": "Is it clear?"}])


def test_local_model_answers_ai_rules(monkeypatch):
    llama = FakeLlama()
    monkeypatch.setattr(local_model, "_client", local_model.LocalClient(llama))
    [result] = run_checks("Worked on it", LLM_STYLE, model=local_model.MODEL_ID)
    assert result.status == FAIL and result.message == "Vague."
    assert llama.calls[0]["temperature"] == 0
    assert llama.calls[0]["response_format"]["schema"] == local_model.ANSWER_SCHEMA


def test_the_prompts_of_all_rules_start_with_the_document(monkeypatch):
    llama = FakeLlama()
    monkeypatch.setattr(local_model, "_client", local_model.LocalClient(llama))
    rules = [{"id": i, "check": "llm", "question": question} for i, question in enumerate(("Is it clear?", "Any blockers?"))]
    run_checks("Worked on it", Style(id="t", name="Test", rules=rules), model=local_model.MODEL_ID)
    first, second = (call["messages"][0]["content"] for call in llama.calls)
    start = first[: first.index("Is it clear?")]
    assert "Worked on it" in start and second.startswith(start)


def test_threads_can_be_set(monkeypatch):
    monkeypatch.delenv("LOCAL_MODEL_THREADS", raising=False)
    monkeypatch.setattr(local_model.os, "cpu_count", lambda: 32)
    assert local_model.threads() == 4
    monkeypatch.setenv("LOCAL_MODEL_THREADS", "2")
    assert local_model.threads() == 2


def test_local_model_is_loaded_once(monkeypatch):
    loads = []
    monkeypatch.setattr(local_model, "_client", None)
    monkeypatch.setattr(local_model, "_load", lambda: loads.append(1) or local_model.LocalClient(FakeLlama()))
    assert local_model.get_client() is local_model.get_client()
    assert len(loads) == 1


def test_local_model_failure_is_skipped_and_never_sent_to_groq(monkeypatch):
    def broken():
        raise RuntimeError("model file missing")

    monkeypatch.setattr(local_model, "_client", None)
    monkeypatch.setattr(local_model, "_load", broken)
    monkeypatch.setitem(sys.modules, "groq", None)  # any use of Groq would fail differently
    [result] = run_checks("text", LLM_STYLE, model=local_model.MODEL_ID)
    assert result.status == SKIP and "model file missing" in result.message


def test_local_model_is_off_until_configured(monkeypatch):
    for name in ("LOCAL_MODEL_PATH", "LOCAL_MODEL_REPO", "LOCAL_MODEL_FILE"):
        monkeypatch.delenv(name, raising=False)
    assert not local_model.is_configured()
    monkeypatch.setenv("LOCAL_MODEL_REPO", "team/model")
    assert not local_model.is_configured()
    monkeypatch.setenv("LOCAL_MODEL_FILE", "model.gguf")
    assert local_model.is_configured()
    assert local_model.MODEL_ID not in llm_checks.MODELS  # the pages add it when it's set up
