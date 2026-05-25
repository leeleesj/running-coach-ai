"""
Running Coach Dashboard — Streamlit 진입점

실행: uv run streamlit run dashboard/main.py
"""

import streamlit as st

st.set_page_config(
    page_title="Running Coach",
    page_icon="🏃",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.switch_page("pages/home.py")
