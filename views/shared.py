import streamlit as st

from checker import local_model, store
from checker.llm_checks import MODELS


@st.cache_data(ttl=60, show_spinner=False)
def _load_styles():
    # An error is returned, not raised, so it's cached too and the app doesn't wait for the database on every click
    try:
        return store.get_store().list_styles(), ""
    except store.StoreError as e:
        return {}, str(e)


def load_style(style_id: str):
    """
    A style from the store (cached for a minute). Falls back to the built-in rules, with a warning, if the
    database can't be reached or doesn't have the style, so checking documents never breaks.
    """
    styles, error = _load_styles()
    if style_id in styles:
        return styles[style_id]
    reason = f"Couldn't load rules from the database ({error})" if error else "The database has no rules for this document"
    st.warning(f"{reason}, so the built-in rules are used.")
    return store.YamlStore().list_styles()[style_id]


def ai_models():
    """
    Models for the dropdowns. The local model is first, so it's the default when it's set up.
    """
    return [local_model.MODEL_ID, *MODELS] if local_model.is_configured() else MODELS


def model_label(model: str) -> str:
    return local_model.label() if model == local_model.MODEL_ID else f"Groq · {model}"


def privacy_note(model: str, document: str) -> str:
    if model == local_model.MODEL_ID:
        return f"The AI model runs inside the app. The {document} isn't sent to an AI service."
    return f"The {document} is sent to Groq for the AI checks."


def clear_styles_cache():
    # Called after every save so all users get the new rules on their next check
    _load_styles.clear()
