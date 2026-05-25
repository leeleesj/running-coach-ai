"""Kraken 디자인 시스템 CSS 주입"""

import streamlit as st

COLORS = {
    "purple":        "#7132f5",
    "purple_subtle": "rgba(133,91,251,0.16)",
    "bg":            "#ffffff",
    "bg_card":       "#f8f8fb",
    "text_primary":  "#101114",
    "text_secondary":"#9497a9",
    "border":        "#dedee5",
    "green":         "#149e61",
    "green_bg":      "rgba(20,158,97,0.16)",
    "green_text":    "#026b3f",
    "warning_bg":    "rgba(251,191,36,0.16)",
    "warning_text":  "#92400e",
    "danger_bg":     "rgba(239,68,68,0.16)",
    "danger_text":   "#991b1b",
    "gray_bg":       "rgba(100,100,100,0.12)",
    "gray_text":     "#555",
}


def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', Helvetica, Arial, sans-serif;
    }

    /* 카드 */
    .kr-card {
        background: #f8f8fb;
        border: 1px solid #dedee5;
        border-radius: 16px;
        padding: 20px 24px;
        box-shadow: rgba(0,0,0,0.03) 0px 4px 24px;
        margin-bottom: 12px;
    }

    /* 대형 숫자 카드 */
    .kr-stat-card {
        background: #f8f8fb;
        border: 1px solid #dedee5;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        box-shadow: rgba(0,0,0,0.03) 0px 4px 24px;
    }
    .kr-stat-value {
        font-size: 48px;
        font-weight: 700;
        color: #7132f5;
        letter-spacing: -1px;
        line-height: 1.1;
        margin-bottom: 4px;
    }
    .kr-stat-label {
        font-size: 14px;
        color: #9497a9;
        font-weight: 400;
    }
    .kr-stat-sub {
        font-size: 13px;
        color: #9497a9;
        margin-top: 6px;
    }
    .kr-stat-sub.green { color: #026b3f; }
    .kr-stat-sub.red   { color: #991b1b; }

    /* 뱃지 */
    .kr-badge {
        display: inline-block;
        border-radius: 6px;
        padding: 3px 10px;
        font-size: 12px;
        font-weight: 500;
    }
    .kr-badge-green   { background: rgba(20,158,97,0.16);  color: #026b3f; }
    .kr-badge-yellow  { background: rgba(251,191,36,0.16); color: #92400e; }
    .kr-badge-red     { background: rgba(239,68,68,0.16);  color: #991b1b; }
    .kr-badge-gray    { background: rgba(100,100,100,0.12);color: #555; }
    .kr-badge-purple  { background: rgba(133,91,251,0.16); color: #5b1ecf; }

    /* 구분선 카드 (left border) */
    .kr-card-green  { border-left: 4px solid #149e61 !important; }
    .kr-card-red    { border-left: 4px solid #ef4444 !important; }
    .kr-card-purple { border-left: 4px solid #7132f5 !important; }
    .kr-card-yellow { border-left: 4px solid #fbbf24 !important; }

    /* 섹션 제목 */
    .kr-section-title {
        font-size: 22px;
        font-weight: 600;
        color: #101114;
        margin: 24px 0 12px 0;
    }

    /* 본문 */
    .kr-body { font-size: 16px; line-height: 1.38; color: #101114; }
    .kr-sub  { font-size: 14px; color: #9497a9; }

    /* Streamlit 기본 패딩 축소 */
    .block-container { padding-top: 2rem !important; }

    /* 테이블 */
    .kr-table { width: 100%; border-collapse: collapse; }
    .kr-table th {
        background: #f8f8fb;
        color: #9497a9;
        font-size: 12px;
        font-weight: 500;
        text-align: left;
        padding: 8px 12px;
        border-bottom: 1px solid #dedee5;
    }
    .kr-table td {
        padding: 10px 12px;
        border-bottom: 1px solid #dedee5;
        font-size: 14px;
        vertical-align: middle;
    }
    .kr-table tr:last-child td { border-bottom: none; }
    </style>
    """, unsafe_allow_html=True)


def stat_card(value: str, label: str, sub: str = "", sub_color: str = "") -> str:
    sub_class = f"class='kr-stat-sub {sub_color}'" if sub_color else "class='kr-stat-sub'"
    sub_html = f"<div {sub_class}>{sub}</div>" if sub else ""
    return (
        f'<div class="kr-stat-card">'
        f'<div class="kr-stat-value">{value}</div>'
        f'<div class="kr-stat-label">{label}</div>'
        f'{sub_html}'
        f'</div>'
    )


def badge(text: str, color: str = "gray") -> str:
    """color: green | yellow | red | gray | purple"""
    return f'<span class="kr-badge kr-badge-{color}">{text}</span>'


def card(content: str, border: str = "") -> str:
    border_class = f"kr-card-{border}" if border else ""
    return f'<div class="kr-card {border_class}">{content}</div>'
