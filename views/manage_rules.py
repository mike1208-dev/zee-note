import copy
import hmac
import os
import uuid

import pandas as pd
import streamlit as st
import yaml

from checker.llm_checks import MODELS
from checker.loader import SUPPORTED_EXTENSIONS, read_document
from checker.report import run_checks, summary, to_dataframe
from checker.rule_import import MAX_CHARS, draft_style
from checker.store import StoreError, YamlStore, get_store
from checker.styles import Style, slugify
from checker.validation import CHECK_TYPES, validate_style
from views.design import page_ready
from views.shared import ai_models, clear_styles_cache, model_label, privacy_note

NEW = "➕ New style"

CHECK_LABELS = {
    "required_sections": "Required sections",
    "no_secrets": "No secrets (keys, passwords)",
    "word_count": "Word count limits",
    "long_sentences": "No very long sentences",
    "forbidden_phrases": "Forbidden words",
    "must_contain": "Must contain text",
    "pattern": "Pattern (regular expression)",
    "mention_at_top": "Tags someone at the top",
    "working_hours": "Working hours in sections",
    "llm": "AI question",
}
DEFAULT_OPTIONS = {
    "required_sections": {"sections": []},
    "word_count": {"max": 500},
    "long_sentences": {"max_words": 35},
    "forbidden_phrases": {"phrases": []},
    "must_contain": {"phrases": []},
    "pattern": {"pattern": "", "must": "match", "label": ""},
    "mention_at_top": {"lines": 3},
    "working_hours": {"sections": []},
    "llm": {"question": ""},
}


def make_draft(style: Style | None) -> dict:
    """
    An editable copy of a style. Each rule gets a stable _uid so its widgets survive deleting others;
    _v changes per draft so widgets don't keep values from the previous style.
    """
    data = copy.deepcopy(style.to_dict()) if style else {"id": "", "name": "", "description": "", "detect": [], "rules": []}
    data["rules"] = [{**rule, "_uid": uuid.uuid4().hex} for rule in data["rules"]]
    data["_v"] = uuid.uuid4().hex
    return data


def draft_to_style(draft: dict) -> Style:
    rules = [{k: v for k, v in rule.items() if k != "_uid"} for rule in draft["rules"]]
    style_id = draft["id"].strip() or slugify(draft["name"])
    return Style.from_dict({**draft, "id": style_id, "rules": rules})


def lines_to_list(text: str, alternatives: bool = False) -> list:
    items = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if alternatives and " / " in line:  # "CI/CD" is one name
            items.append([part.strip() for part in line.split(" / ") if part.strip()])
        else:
            items.append(line.strip())
    return items


def list_to_lines(values) -> str:
    values = values if isinstance(values, list) else [values] if values else []
    return "\n".join(" / ".join(map(str, v)) if isinstance(v, list) else str(v) for v in values)


def as_number(value, default: int, minimum: int = 0) -> int:
    """
    A value the number field accepts, even if the AI or the database gave something else.
    """
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError, OverflowError):
        return default


def rule_fields(rule: dict, key: str) -> None:
    """
    Form fields for one rule; edits the rule dict in place.
    """
    col1, col2 = st.columns([2, 1])
    rule["title"] = col1.text_input("Title (shown in the report)", str(rule.get("title") or ""), key=f"{key}_title")
    rule["id"] = col2.text_input("Rule ID", str(rule.get("id") or ""), key=f"{key}_id")
    check = rule.get("check")

    if check in ("required_sections", "working_hours"):
        text = st.text_area(
            "Sections, one per line. Accept alternatives with / between spaces, e.g. Blockers / Issues",
            list_to_lines(rule.get("sections")),
            key=f"{key}_sections",
        )
        rule["sections"] = lines_to_list(text, alternatives=True)
    elif check in ("forbidden_phrases", "must_contain"):
        text = st.text_area("Words or phrases, one per line", list_to_lines(rule.get("phrases")), key=f"{key}_phrases")
        rule["phrases"] = lines_to_list(text)
    elif check == "word_count":
        col1, col2 = st.columns(2)
        minimum = col1.number_input("Minimum words (0 = none)", min_value=0, value=as_number(rule.get("min"), 0), key=f"{key}_min")
        maximum = col2.number_input("Maximum words (0 = none)", min_value=0, value=as_number(rule.get("max"), 0), key=f"{key}_max")
        rule.pop("min", None)
        rule.pop("max", None)
        if minimum:
            rule["min"] = int(minimum)
        if maximum:
            rule["max"] = int(maximum)
    elif check == "long_sentences":
        rule["max_words"] = int(
            st.number_input(
                "Longest allowed sentence (words)", min_value=5, value=as_number(rule.get("max_words"), 35, 5), key=f"{key}_max_words"
            )
        )
    elif check == "pattern":
        rule["pattern"] = st.text_input(
            "Regular expression", str(rule.get("pattern") or ""), key=f"{key}_pattern", help=r"e.g. [A-Z]+-\d+ for ticket numbers like ABC-123"
        )
        rule["must"] = st.radio(
            "The pattern...",
            ["match", "not_match"],
            index=0 if rule.get("must", "match") == "match" else 1,
            format_func={"match": "must appear", "not_match": "must not appear"}.get,
            horizontal=True,
            key=f"{key}_must",
        )
        rule["label"] = st.text_input("What it means (used in the report), e.g. ticket number", str(rule.get("label") or ""), key=f"{key}_label")
    elif check == "llm":
        rule["question"] = st.text_area(
            "Yes/no question for the AI ('yes' = the rule is followed)", str(rule.get("question") or ""), key=f"{key}_question"
        )
        text = st.text_area(
            "Known terms that need no explanation, one per line (optional)", list_to_lines(rule.get("known_terms")), key=f"{key}_known_terms"
        )
        rule.pop("known_terms", None)
        if terms := lines_to_list(text):
            rule["known_terms"] = terms
    elif check == "mention_at_top":
        rule["lines"] = int(
            st.number_input("Lines that count as the top", min_value=1, value=as_number(rule.get("lines"), 3, 1), key=f"{key}_lines")
        )
    elif check == "no_secrets":
        st.caption("No options: finds API keys, tokens and passwords.")
    else:
        st.warning(f"Unknown check type '{check}'. Delete this rule or fix it.")


page_ready()
st.title("⚙️ Manage rules")

store = get_store()
if not store.editable:
    st.info(
        "Rules are read from the rules/*.yaml files. To edit rules here, connect a Supabase database "
        "(SUPABASE_URL and SUPABASE_KEY in Secrets). See the README."
    )
    st.stop()

password = os.getenv("EDITOR_PASSWORD")
if not password:
    st.warning("Editing is turned off. Set EDITOR_PASSWORD in Secrets to turn it on.")
    st.stop()

if not st.session_state.get("editor_name"):
    with st.form("login"):
        entered = st.text_input("Editor password", type="password")
        name = st.text_input("Your name (saved with each change)")
        if st.form_submit_button("Unlock"):
            if hmac.compare_digest(entered.encode(), password.encode()) and name.strip():
                st.session_state.editor_name = name.strip()
                st.rerun()
            st.error("Wrong password, or the name is missing.")
    st.stop()

editor = st.session_state.editor_name
st.caption(f"Signed in as **{editor}** · rules are stored in the {store.label} · changes apply to checks right away")

if message := st.session_state.pop("flash", None):
    st.success(message)

try:
    with st.spinner("Loading the rules..."):
        styles = store.list_styles()
except StoreError as e:
    st.error(str(e))
    st.stop()

if not styles:
    st.info("The database has no styles yet.")
    if st.button("Load the example rules (Daily report, Issue/PR, Work plan)"):
        try:
            store.save_styles(list(YamlStore().list_styles().values()), editor)
        except StoreError as e:
            st.error(str(e))
        else:
            clear_styles_cache()
            st.session_state.flash = "Example rules loaded."
            st.rerun()

edit_tab, import_tab, history_tab = st.tabs(["Edit styles", "Import from rule document", "History"])

with edit_tab:
    # Requests from buttons in other tabs, applied before the style selector is drawn
    if "pending_draft" in st.session_state:
        st.session_state.draft = st.session_state.pop("pending_draft")
        st.session_state.style_choice = st.session_state.draft_for = NEW
    if "pending_choice" in st.session_state:
        st.session_state.style_choice = st.session_state.pop("pending_choice")

    options = [NEW, *styles]
    if st.session_state.get("style_choice") not in options:
        st.session_state.style_choice = NEW
    choice = st.selectbox(
        "Style", options, format_func=lambda i: i if i == NEW else f"{styles[i].name} ({i})", key="style_choice"
    )
    if st.session_state.get("draft_for") != choice:
        st.session_state.draft = make_draft(None if choice == NEW else styles[choice])
        st.session_state.draft_for = choice
    draft = st.session_state.draft
    is_new = choice == NEW
    v = draft["_v"]

    col1, col2 = st.columns(2)
    draft["name"] = col1.text_input("Name", draft["name"], key=f"{v}_name", placeholder="e.g. Meeting notes")
    if is_new:
        draft["id"] = col2.text_input("ID (leave empty to make one from the name)", draft["id"], key=f"{v}_id")
    else:
        col2.text_input("ID", draft["id"], disabled=True, key=f"{v}_id")
    draft["description"] = st.text_input("Description", draft["description"], key=f"{v}_description")
    detect = st.text_input(
        "Auto-detect words, comma-separated (e.g. meeting notes, attendees)", ", ".join(draft["detect"]), key=f"{v}_detect"
    )
    draft["detect"] = [word.strip() for word in detect.split(",") if word.strip()]

    st.subheader("Rules")
    for rule in list(draft["rules"]):
        uid = rule["_uid"]
        title = rule.get("title") or "Untitled rule"
        with st.expander(f"{title} · {CHECK_LABELS.get(rule.get('check'), rule.get('check'))}", expanded=not rule.get("title")):
            rule_fields(rule, f"{v}_{uid}")
            if st.button("🗑️ Delete rule", key=f"{v}_{uid}_delete"):
                draft["rules"] = [r for r in draft["rules"] if r["_uid"] != uid]
                st.rerun()

    col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
    new_check = col1.selectbox("Add a rule of type", CHECK_TYPES, format_func=CHECK_LABELS.get, key=f"{v}_new_check")
    if col2.button("➕ Add rule", key=f"{v}_add", width="stretch"):
        draft["rules"].append(
            {
                "id": f"{new_check}_{len(draft['rules']) + 1}",
                "title": "",
                "check": new_check,
                **copy.deepcopy(DEFAULT_OPTIONS.get(new_check, {})),
                "_uid": uuid.uuid4().hex,
            }
        )
        st.rerun()

    with st.expander("🧪 Test these rules on a sample document (before saving)"):
        sample = st.text_area("Sample document", key=f"{v}_sample")
        include_ai = st.toggle("Include AI rules", value=False, key=f"{v}_sample_ai")
        test_model = st.selectbox(
            "AI model", ai_models(), format_func=model_label, disabled=not include_ai, key=f"{v}_sample_model"
        )
        if include_ai:
            st.caption(privacy_note(test_model, "sample"))
        if st.button("Run test", key=f"{v}_run_test"):
            results = run_checks(sample, draft_to_style(draft), use_llm=include_ai, model=test_model)
            st.markdown(f"**{summary(results)}**")
            st.dataframe(to_dataframe(results), hide_index=True, width="stretch")

    st.divider()
    col1, col2 = st.columns(2)
    if col1.button("💾 Save style", type="primary", key=f"{v}_save"):
        style = draft_to_style(draft)
        problems = validate_style(style)
        if is_new and style.id in styles:
            problems.append(f"A style with the ID '{style.id}' already exists. Choose another ID.")
        if problems:
            for problem in problems:
                st.error(problem)
        else:
            try:
                store.save_style(style, editor)
            except StoreError as e:
                st.error(str(e))
            else:
                clear_styles_cache()
                st.session_state.pending_choice = style.id
                st.session_state.draft_for = None  # reload the saved version from the database
                st.session_state.flash = f"Saved '{style.name}'. Checks use it right away."
                st.rerun()

    built_in = YamlStore().list_styles().get(choice)
    if built_in:
        with col2.popover("🔄 Use the built-in rules"):
            st.write(f"Replace the rules of **{draft['name']}** with the built-in ones? You can undo it from the History tab.")
            if st.button("Yes, replace them", key=f"{v}_confirm_built_in"):
                try:
                    store.save_style(built_in, editor)
                except StoreError as e:
                    st.error(str(e))
                else:
                    clear_styles_cache()
                    st.session_state.draft_for = None  # reload the saved version from the database
                    st.session_state.flash = f"'{built_in.name}' now uses the built-in rules."
                    st.rerun()

    if not is_new:
        with col2.popover("🗑️ Delete style"):
            st.write(f"Delete **{draft['name']}**? You can bring it back from the History tab.")
            if st.button("Yes, delete it", key=f"{v}_confirm_delete"):
                try:
                    store.delete_style(draft["id"])
                except StoreError as e:
                    st.error(str(e))
                else:
                    clear_styles_cache()
                    st.session_state.pending_choice = NEW
                    st.session_state.flash = f"Deleted '{draft['name']}'."
                    st.rerun()

with import_tab:
    st.write(
        "Upload or paste a rule document for one kind of document. The AI drafts the rules, "
        "then you review and save them in the **Edit styles** tab."
    )
    rule_file = st.file_uploader("Rule document", type=[ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS], key="import_file")
    rule_text = st.text_area("...or paste the rules here", height=200, key="import_text")
    import_model = st.selectbox("Groq model", MODELS, key="import_model")
    if st.button("✨ Draft rules with AI", type="primary"):
        try:
            text = read_document(rule_file.name, rule_file.getvalue()) if rule_file else rule_text
        except Exception as e:
            st.error(f"Could not read the file: {e}")
            text = ""
        if not text.strip():
            st.warning("Upload a file or paste the rules first.")
        else:
            with st.spinner("Drafting rules..."):
                try:
                    style = draft_style(text, model=import_model)
                except Exception as e:
                    st.error(f"Couldn't draft rules: {e}")
                    style = None
            if style:
                if style.id in styles:
                    style.id = f"{style.id}_new"
                st.session_state.pending_draft = make_draft(style)
                problems = validate_style(style)
                note = f" Fix these before saving: {' '.join(problems)}" if problems else ""
                if len(text) > MAX_CHARS:
                    note += f" Only the first {MAX_CHARS} characters of the rule document were used."
                st.session_state.flash = (
                    f"Draft '{style.name}' with {len(style.rules)} rules is ready in the Edit styles tab. "
                    f"Review it, test it, then save.{note}"
                )
                st.rerun()

with history_tab:
    try:
        rows = store.history()
    except StoreError as e:
        st.error(str(e))
        rows = []
    if not rows:
        st.info("No changes yet. Every save or delete keeps the previous version here.")
    else:
        st.caption("Each row is a style as it was **before** a change. Restore it to undo that change.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "When": row["archived_at"][:16].replace("T", " "),
                        "Style": row["style_id"],
                        "Change": row["action"],
                        "Version saved by": row["updated_by"],
                        "Rules": len(row["rules"] or []),
                    }
                    for row in rows
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        labels = {
            row["history_id"]: f"{row['archived_at'][:16].replace('T', ' ')} · {row['style_id']} (before {row['action']})"
            for row in rows
        }
        picked = st.selectbox("Version", list(labels), format_func=labels.get)
        row = next(r for r in rows if r["history_id"] == picked)
        st.code(
            yaml.safe_dump(
                {k: row[k] for k in ("name", "description", "detect", "rules")}, allow_unicode=True, sort_keys=False
            ),
            language="yaml",
        )
        if st.button("↩️ Restore this version"):
            try:
                store.restore(row, editor)
            except StoreError as e:
                st.error(str(e))
            else:
                clear_styles_cache()
                st.session_state.pending_choice = row["style_id"]
                st.session_state.draft_for = None
                st.session_state.flash = f"Restored '{row['name']}'."
                st.rerun()
