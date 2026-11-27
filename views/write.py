import re
from datetime import datetime, timedelta, timezone
from html import escape

import streamlit as st

from checker.basic_checks import no_secrets
from checker.llm_checks import MODELS
from checker.markup import escape_markdown, to_html, to_slack
from checker.report import count, run_checks
from checker.result import FAIL, ICONS, PASS, SKIP
from checker.store import YamlStore
from checker.writer import GREETING, TO_FILL_IN, Settings, WriterError, extract, render, rules_for_report, settings_questions, unknown_terms
from views.design import REPORT_SKELETON, card_title, page_ready
from views.points import AI_OFF, points_to_check
from views.shared import load_style, model_label

STYLE_ID = "daily_report"
REPO = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+")
JST = timezone(timedelta(hours=9))  # the server's clock may be in another country

SAMPLE = """issue 95 fix booking list shows the wrong date, pr 102 merged
issue 96 feat send an email when the password is reset, pr 101 in review
practiced the project presentation
today: issue 97 chore add validation to the password reset form
blocker: waiting for QA validation on staging"""

# Slack takes its own format, other editors take the HTML, and plain text boxes take the Markdown. Only the copy event can set
# Slack's format, so the newer clipboard API is the backup
COPY_JS = """export default function ({ data, parentElement }) {
  const button = parentElement.querySelector("button");
  const blob = type => new Blob([data[type]], { type });
  button.onclick = async () => {
    let copied = false;
    const copy = event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      for (const type in data) event.clipboardData.setData(type, data[type]);
      copied = true;
    };
    document.addEventListener("copy", copy, true);
    document.execCommand("copy");
    document.removeEventListener("copy", copy, true);
    try {
      if (!copied) await navigator.clipboard.write([new ClipboardItem({ "text/plain": blob("text/plain"), "text/html": blob("text/html") })]);
      button.textContent = "Copied ✓";
    } catch {
      button.textContent = "Couldn't copy: use the Markdown tab";
    }
    setTimeout(() => { button.textContent = "Copy for Slack"; }, 2500);
  };
}"""
COPY_CSS = """button { padding: 9px 20px; border: 0; border-radius: 8px; background: var(--st-primary-color); color: var(--zc-on-main);
  font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
button:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: 2px; }"""
copy_button = st.components.v2.component("copy_report", html="<button>Copy for Slack</button>", css=COPY_CSS, js=COPY_JS)


def use_sample():
    st.session_state.notes = SAMPLE


def use_report(text: str):
    written = st.session_state["written"]
    if "ai_rules" in st.session_state and st.session_state["ai_rules"][0] == written.get("report"):
        st.session_state["ai_rules"] = (text, st.session_state["ai_rules"][1])  # settings don't change the results of the AI
    st.session_state.report_text = written["report"] = text


def show_check(written: dict, text: str, model: str, settings: Settings):
    """
    One closed line with all that is left to check. The details open with a click.
    """
    with st.spinner("Loading the rules..."):  # only here, so the page itself never waits for the database
        style = rules_for_report(load_style(STYLE_ID), YamlStore().list_styles()[STYLE_ID])
    if st.session_state.get("check_ai"):
        if no_secrets(text, {}).status != PASS:
            st.error("The report may contain a key or password, so it wasn't sent to the AI service.")
        else:
            with st.spinner("Checking the rules..."):
                st.session_state["ai_rules"] = (text, {result.rule_id: result for result in run_checks(text, style, model=model)})
        st.session_state.check_ai = False  # only now, so a click during the check doesn't lose it
    checked_text, checked = st.session_state.get("ai_rules", ("", {}))
    results = run_checks(text, style, use_llm=False)
    if checked_text == text:  # an edited report needs a new check
        results = [checked.get(result.rule_id, result) if result.message == AI_OFF else result for result in results]

    questions = settings_questions(written["draft"], settings) + written["draft"].questions
    if written["days"] != (settings.day, settings.first_section):
        questions.insert(0, "The date or the first section changed. Click Write daily report again to sort the tasks for the new day.")
    if terms := unknown_terms(written["draft"], [term for rule in style.rules for term in rule.get("known_terms") or []]):
        questions.append("A reader who isn't technical may not know: " + ", ".join(terms))
    points = points_to_check(questions, results, edited=text != written["report"])
    found = f"{len(points)} point{'' if len(points) == 1 else 's'} to check" if points else "Nothing to check"

    off = sum(result.message == AI_OFF for result in results)
    rules = f"{count(results, PASS)} of {len(results) - off} rules passed" + (f", {off} not checked yet" if off else "")

    with st.expander(f"{found} · {rules}", key="check_box", icon="⚠️" if points else "✅"):
        st.markdown("\n".join(f"- {escape_markdown(point)}" for point in points))
        items = ""
        for result in results:
            mark = {PASS: "✓", SKIP: "–"}.get(result.status, "!")
            items += f'<li class="{"off" if result.message == AI_OFF else result.status}"><span>{mark}</span> {escape(result.title)}</li>'
        st.html(f'<ul class="zc-rules">{items}</ul>')
        if count(results, SKIP):
            st.button("Check again", help="Sends the edited report to Groq", on_click=ask_for, args=("check_ai",))


def ask_for(name: str):
    st.session_state[name] = True


def find_problems() -> dict[str, str]:
    """
    What is wrong in the fields, by the key of the field. All but the repo link and the greeting are required.
    """
    state, problems = st.session_state, {}
    if not state.get("notes", "").strip():
        problems["notes"] = "Write your notes."
    if not state.get("reviewer", "").strip(" @"):
        problems["reviewer"] = "Write the reviewer's name."
    for key, name in (("done_hours", state.get("first_section", "Yesterday")), ("plan_hours", "Today")):
        if state.get(key) is None:
            problems[key] = f"Write the hours for {name}."
    repo = state.get("repo", "").strip().rstrip("/")
    if repo and not REPO.fullmatch(repo):
        problems["repo"] = "Write a repo link such as https://github.com/acme/app, or leave it empty."
    return problems


def start_writing():
    st.session_state.validate = True
    st.session_state.writing = not find_problems()


def show_problem(key: str):
    message = find_problems().get(key)
    if message and st.session_state.get("validate"):  # after the first click on "Write daily report"
        st.html(f'<p class="zc-error">{escape(message)}</p>')


def restore(key: str, default):
    """
    For fields whose first value is set by code: Streamlit's own persist_state would be overwritten by it.
    """
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get("kept", {}).get(key, default)


def keep(key: str, value):
    st.session_state.setdefault("kept", {})[key] = value
    return value


def settings_panel(locked: bool) -> tuple[Settings, str]:
    common = {"disabled": locked, "persist_state": "session"}
    with st.container(border=True, key="settings"):
        card_title("Settings", "These values go straight into the report. The AI never changes them.")
        reviewer = st.text_input("Reviewer name", key="reviewer", placeholder="e.g. Sam", **common)
        show_problem("reviewer")
        today, state = datetime.now(JST).date(), st.session_state
        restore("day", today)
        if state.day == state.get("default_day", today) and not state.get("written"):
            state.day = state.default_day = today  # a chosen date and the date of a written report stay after midnight
        day = keep("day", st.date_input("Report date", key="day", disabled=locked))
        first_section = st.selectbox("First section", ["Yesterday", "Weekend"], key="first_section", **common)
        hours = []
        for column, name, key in zip(st.columns(2, wrap=False), (first_section, "Today"), ("done_hours", "plan_hours")):
            restore(key, 7.0)  # not "value", because a field with a value can't be emptied
            with column:
                label = f"{name} :small[(hours)]"
                hours.append(keep(key, st.number_input(label, 0.0, 24.0, value=None, step=0.5, format="%g", key=key, disabled=locked)))
                show_problem(key)
        repo = st.text_input("GitHub repo link :small[(optional)]", key="repo", placeholder="https://github.com/acme/app", **common)
        show_problem("repo")
        greeting = st.text_area("Greeting :small[(optional)]", value=GREETING, key="greeting", height=80, **common)
        with st.expander("AI model"):
            model = st.selectbox("AI model", MODELS, format_func=model_label, key="writer_model", label_visibility="collapsed", **common)
    return Settings(day, reviewer, first_section, *hours, repo.strip().rstrip("/"), greeting), model


def write_report(notes: str, model: str, settings: Settings):
    """
    The page is locked while the AI writes. The rerun at the end unlocks it.
    """
    for key in ("written", "ai_rules", "write_error"):  # don't leave an old report next to new notes
        st.session_state.pop(key, None)
    try:
        with st.spinner("Writing your daily report..."):
            st.html(REPORT_SKELETON)
            draft = extract(notes, model=model, day=settings.day, first_section=settings.first_section)
            st.session_state["written"] = {"draft": draft, "days": (settings.day, settings.first_section)}
        use_report(render(st.session_state["written"]["draft"], settings))
        ask_for("check_ai")
    except WriterError as e:
        st.session_state["write_error"] = str(e)
    except Exception:
        st.session_state.writing = False
        raise
    st.session_state.writing = False
    st.rerun()


def show_report(written: dict, model: str, settings: Settings):
    missing = find_problems().keys() - {"notes"}
    report = written["report"] if missing else render(written["draft"], settings)
    changed = report != written["report"]
    if changed and st.session_state.report_text == written["report"]:  # not edited, so the settings can be used at once
        use_report(report)
        changed = False
    if changed:
        st.warning("**Settings changed** after you edited the report, so they aren't in it yet.")
        st.button("Use the new settings (your edits will be lost)", on_click=use_report, args=(report,))

    preview, markdown = st.tabs(["Preview", "Markdown (edit)"], key="report_view")
    with markdown:
        text = st.text_area("Daily report in Markdown", height=430, key="report_text", label_visibility="collapsed", persist_state="session")
    with preview:
        st.html(f'<div class="zc-preview">{to_html(text)}</div>')
    if any(part in text for part in TO_FILL_IN):
        st.error(f"{ICONS[FAIL]} Fill in the parts in [brackets] before you post it.")

    check_box = st.container()  # filled last, so the buttons are there during the check
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        name = f"daily-report-{settings.day}.md"
        st.download_button("Download .md", text + "\n", file_name=name, mime="text/markdown", on_click="ignore")
        copy_button(data={"text/plain": text, "text/html": to_html(text), "slack/texty": to_slack(text)}, key="copy", width="content")
    with check_box:
        show_check(written, text, model, settings)


page_ready()
locked = bool(st.session_state.get("writing"))
left, right = st.columns([5, 2])

with right:
    settings, model = settings_panel(locked)

with left:
    with st.container(border=True, key="notes_card"):
        card_title(
            "Your notes",
            "Write what you did, what you'll do, and any blockers. Any order is fine. The notes and the report are sent to Groq, so don't write keys or passwords.",
        )
        notes = st.text_area(
            "Your notes", height=190, key="notes", placeholder="e.g. fixed issue 95, pr 102 merged…", label_visibility="collapsed",
            disabled=locked, persist_state="session",
        )
        show_problem("notes")
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            st.button("Use sample notes", on_click=use_sample, disabled=locked)
            st.button("Writing..." if locked else "Write daily report", key="write", type="primary", on_click=start_writing, disabled=locked)

    with st.container(border=True, key="report_card"):
        card_title("Your daily report", "Check it, edit it, and copy it to Slack.")
        if locked:
            write_report(notes, model, settings)
        elif written := st.session_state.get("written"):
            show_report(written, model, settings)
        elif error := st.session_state.get("write_error"):
            st.error(error)
        else:
            st.html('<div class="zc-empty">Write your notes and click <strong>Write daily report</strong>. The report shows up here.</div>')
