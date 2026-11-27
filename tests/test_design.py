from pathlib import Path

from streamlit.testing.v1 import AppTest


def app():
    import streamlit as st

    from views.design import page_ready, show_skeleton

    show_skeleton(st.session_state.get("page", "Write"))
    if not st.session_state.get("loading"):
        page_ready()
    st.button("Rerun")


def shown(at):
    return any("zc-skeleton" in h.proto.body for h in at.get("html"))


def test_the_skeleton_shows_until_the_page_is_ready():
    at = AppTest.from_function(app)
    at.session_state.loading = True
    assert shown(at.run())
    at.session_state.loading = False
    assert not shown(at.run())
    at.session_state.loading = True
    assert not shown(at.run())  # a rerun of the same page doesn't flash
    at.session_state.page = "Manage rules"
    assert shown(at.run())


def test_manage_rules_is_turned_off(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.exception
    link = at.get("page_link")[0].proto
    assert link.label == "Manage rules" and link.disabled
