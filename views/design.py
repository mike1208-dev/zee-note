from html import escape
from pathlib import Path

import streamlit as st

# The colors that Streamlit's theme (.streamlit/config.toml) doesn't have
COLORS = {
    "light": {"card": "#fff", "soft": "#667085", "line": "#d9dee7", "ok": "#13795b", "warn": "#8a5a00", "warn-soft": "#fff6e0", "error": "#c0271d", "on-main": "#fff"},
    "dark": {"card": "#1d212c", "soft": "#9aa4b8", "line": "#343b4b", "ok": "#54c79c", "warn": "#f0c36a", "warn-soft": "#332c1b", "error": "#ff8a80", "on-main": "#1d212c"},
}

SKELETON = (
    '<div class="zc-skeleton" role="status" aria-label="Loading"><div class="zc-card"><i style="width:30%"></i><i style="width:75%"></i><b></b></div>'
    '<div class="zc-card"><i style="width:50%"></i>' + '<i></i><i class="field"></i>' * 5 + "</div></div>"
)
REPORT_SKELETON = (
    '<div class="zc-skeleton zc-report" aria-hidden="true"><i style="width:15%"></i><i style="width:60%"></i><i style="width:40%"></i>'
    + "".join(f'<i style="width:{width}%;margin-left:{indent}px"></i>' for width, indent in ((25, 0), (55, 24), (45, 48), (60, 24), (45, 48), (20, 0), (50, 24)))
    + "</div>"
)


def use_design():
    colors = COLORS[st.context.theme.type or "light"]
    st.html("<style>:root {" + "".join(f"--zc-{name}: {value};" for name, value in colors.items()) + "}</style>")
    st.html(Path(__file__).with_name("design.css"))


def show_header(other_page, disabled: bool = False):
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center", key="header"):
        st.html("<h1>📝 ZeeChecker</h1><p>Write plain notes. Get a daily report that is ready to post.</p>", width="content")
        st.page_link(other_page, disabled=disabled)


def show_skeleton(page_name: str):
    """
    Gray shapes in the place of the page, until the page calls page_ready. Not on the later reruns of the same page.
    """
    place = st.empty()  # always there, so the elements after it keep their places
    if st.session_state.get("ready_page") != page_name:
        place.html(SKELETON)
    st.session_state["skeleton"] = (page_name, place)


def page_ready():
    if "skeleton" in st.session_state:  # not when the page runs alone in a test
        st.session_state["ready_page"], place = st.session_state.pop("skeleton")
        place.empty()


def card_title(title: str, text: str):
    st.html(f'<div class="zc-title"><h2>{escape(title)}</h2><p>{escape(text)}</p></div>')
