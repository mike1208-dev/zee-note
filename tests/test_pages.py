"""
Runs the Streamlit pages headlessly with an in-memory database, so UI errors show up in tests.
"""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import checker.rule_import
import checker.store
from checker import llm_checks, local_model
from checker.store import StoreError
from checker.styles import Style


class MemoryStore:
    editable = True
    label = "test database"

    def __init__(self):
        self.styles, self.rows = {}, []

    def list_styles(self):
        return dict(self.styles)

    def save_style(self, style, editor):
        if style.id in self.styles:
            self.rows.insert(0, {**self.styles[style.id].to_dict(), "style_id": style.id, "history_id": len(self.rows) + 1,
                                 "action": "update", "archived_at": "2026-11-20T10:00:00", "updated_by": editor})
        self.styles[style.id] = Style.from_dict(style.to_dict())

    def save_styles(self, styles, editor):
        for style in styles:
            self.save_style(style, editor)

    def delete_style(self, style_id):
        self.styles.pop(style_id)

    def history(self, limit=50):
        return self.rows

    def restore(self, row, editor):
        self.save_style(Style.from_dict({**row, "id": row["style_id"]}), editor)


@pytest.fixture(autouse=True)
def clean_start(monkeypatch):
    st.cache_data.clear()  # or a test gets the rules of the one before it
    for name in ("LOCAL_MODEL_PATH", "LOCAL_MODEL_REPO", "LOCAL_MODEL_FILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def memory_store(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(checker.store, "get_store", lambda: store)
    monkeypatch.setenv("EDITOR_PASSWORD", "secret")
    return store


def test_manage_page_needs_the_password(memory_store):
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    assert not at.exception
    at.text_input[0].input("wrong")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    assert any("Wrong password" in e.value for e in at.error)


def test_manage_page_loads_examples_edits_and_restores(memory_store):
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    assert not at.exception

    # Empty database -> load the example rules
    next(b for b in at.button if b.label.startswith("Load the example rules")).click().run()
    assert set(memory_store.styles) == {"daily_report", "issue_pr", "work_plan"}

    # Open a style, rename it and save
    at.selectbox(key="style_choice").set_value("daily_report").run()
    name_box = next(t for t in at.text_input if t.label == "Name")
    name_box.input("Daily report v2").run()
    next(b for b in at.button if b.label == "💾 Save style").click().run()
    assert not at.exception
    assert memory_store.styles["daily_report"].name == "Daily report v2"
    assert memory_store.rows[0]["name"] == "Daily report"  # old version kept in history

    # Restore the old version from History
    next(b for b in at.button if b.label == "↩️ Restore this version").click().run()
    assert memory_store.styles["daily_report"].name == "Daily report"


def test_manage_page_replaces_old_rules_with_the_built_in_ones(memory_store):
    memory_store.styles["daily_report"] = Style(id="daily_report", name="Old", rules=[{"id": "old", "check": "no_secrets"}])
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    at.selectbox(key="style_choice").set_value("daily_report").run()
    next(b for b in at.button if b.label == "Yes, replace them").click().run()
    assert not at.exception
    assert len(memory_store.styles["daily_report"].rules) == 8
    assert memory_store.rows[0]["name"] == "Old"


def test_manage_page_tests_rules_with_the_chosen_model(memory_store, monkeypatch):
    models = []
    monkeypatch.setattr(llm_checks, "default_client", lambda model: models.append(model))  # no client: skipped
    monkeypatch.setenv("LOCAL_MODEL_PATH", "model.gguf")
    memory_store.styles["daily_report"] = Style(id="daily_report", name="Daily", rules=[{"id": "clear", "check": "llm"}])
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    at.selectbox(key="style_choice").set_value("daily_report").run()
    next(t for t in at.toggle if t.label == "Include AI rules").set_value(True).run()
    assert any("isn't sent to an AI service" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Run test").click().run()
    assert not at.exception
    assert models == [local_model.MODEL_ID]

    model_box = next(s for s in at.selectbox if s.label == "AI model")
    groq_model = llm_checks.MODELS[0]
    model_box.set_value(groq_model).run()
    assert any("sent to Groq" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "Run test").click().run()
    assert models == [local_model.MODEL_ID, groq_model]


def test_manage_page_shows_an_error_when_the_example_rules_cannot_be_saved(memory_store, monkeypatch):
    def read_only(styles, editor):
        raise StoreError("Supabase error 403")

    monkeypatch.setattr(memory_store, "save_styles", read_only)
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    next(b for b in at.button if b.label.startswith("Load the example rules")).click().run()
    assert not at.exception
    assert any("403" in e.value for e in at.error)


def test_manage_page_opens_a_style_with_wrong_option_values(memory_store):
    rules = [
        {"id": "a", "check": "word_count", "min": "50", "max": "about 500"},
        {"id": "b", "check": "long_sentences", "max_words": None},
        {"id": "c", "check": "mention_at_top", "lines": 0},
        {"id": "d", "check": "required_sections", "sections": None},
        {"id": "e", "check": "must_contain", "phrases": "Ticket"},
        {"id": "f", "check": "pattern", "pattern": None, "label": 3},
        {"id": "g", "title": 5, "check": "llm", "question": ["Is it clear?"]},
        {"id": "h", "check": "required_sections", "sections": ["CI/CD", ["Blockers", "Issues"]]},
    ]
    memory_store.styles["daily_report"] = Style(id="daily_report", name="Daily", rules=rules)
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    at.selectbox(key="style_choice").set_value("daily_report").run()
    assert not at.exception
    saved = {rule["id"]: rule for rule in at.session_state["draft"]["rules"]}
    assert saved["a"]["min"] == 50 and "max" not in saved["a"]
    assert saved["b"]["max_words"] == 35 and saved["c"]["lines"] == 1
    assert saved["e"]["phrases"] == ["Ticket"]
    assert saved["h"]["sections"] == ["CI/CD", ["Blockers", "Issues"]]


def test_manage_page_says_when_a_rule_document_is_too_long(memory_store, monkeypatch):
    drafted = Style(id="notes", name="Notes", rules=[{"id": "a", "title": "A", "check": "word_count", "max": "about 500"}])
    monkeypatch.setattr(checker.rule_import, "draft_style", lambda text, model: drafted)
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()
    at.text_area(key="import_text").input("x" * 12001).run()
    next(b for b in at.button if b.label == "✨ Draft rules with AI").click().run()
    assert not at.exception
    message = " ".join(s.value for s in at.success)
    assert "'max' must be a whole number" in message and "first 12000 characters" in message


def test_manage_page_creates_a_new_style(memory_store):
    at = AppTest.from_file("../views/manage_rules.py", default_timeout=30).run()
    at.text_input[0].input("secret")
    at.text_input[1].input("Mike")
    at.button[0].click().run()

    next(t for t in at.text_input if t.label == "Name").input("Meeting notes").run()
    next(b for b in at.button if b.label == "➕ Add rule").click().run()  # first type in the list: required_sections
    next(t for t in at.text_input if t.label == "Title (shown in the report)").input("Has attendees").run()
    next(t for t in at.text_area if t.label.startswith("Sections")).input("Attendees\nAction items / Next steps").run()
    next(b for b in at.button if b.label == "💾 Save style").click().run()
    assert not at.exception, at.exception
    saved = memory_store.styles["meeting_notes"]
    assert saved.rules[0]["sections"] == ["Attendees", ["Action items", "Next steps"]]
    assert "_uid" not in saved.rules[0]
