import streamlit as st
from dotenv import load_dotenv

from views.design import show_header, show_skeleton, use_design

load_dotenv()  # GROQ_API_KEY, SUPABASE_* etc. from .env, before the pages read their settings

st.set_page_config(page_title="ZeeChecker", page_icon="📝", layout="wide")

write = st.Page("views/write.py", title="Write daily report", icon="📝", default=True)
rules = st.Page("views/manage_rules.py", title="Manage rules", icon="⚙️")
page = st.navigation([write, rules], position="hidden")

use_design()
if page == write:
    show_header(rules, disabled=True)  # turned off for now
else:
    show_header(write)
show_skeleton(page.title)
page.run()
