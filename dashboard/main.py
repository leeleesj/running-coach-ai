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

pages = [
    st.Page("pages/home.py",    title="홈",         icon="🏠", default=True),
    st.Page("pages/weekly.py",  title="이번 주",     icon="📋"),
    st.Page("pages/monthly.py", title="월간 트래킹", icon="📈"),
    st.Page("pages/settings.py",title="설정",        icon="⚙️"),
]

pg = st.navigation(pages)
pg.run()
