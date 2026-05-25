"""Plotly 차트 컴포넌트 (Kraken 스타일)"""

import plotly.graph_objects as go
import plotly.express as px

PURPLE = "#7132f5"
PURPLE_FILL = "rgba(113,50,245,0.08)"
GRID_COLOR = "#dedee5"
GREEN = "#149e61"
RED = "#ef4444"
YELLOW = "#fbbf24"


def _base_layout(title: str = "", height: int = 250) -> dict:
    return dict(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=30 if title else 10, b=10),
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(family="IBM Plex Sans, Helvetica, Arial", size=12, color="#101114"),
        xaxis=dict(gridcolor=GRID_COLOR, showgrid=True, zeroline=False),
        yaxis=dict(gridcolor=GRID_COLOR, showgrid=True, zeroline=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        showlegend=True,
    )


def vdot_trend_chart(history: list[dict]) -> go.Figure:
    """VDOT 추이 라인 차트 (score_history)"""
    if not history:
        return go.Figure()

    labels = [h["week_start"][5:] for h in history]  # MM-DD
    values = [h["vdot"] for h in history if h.get("vdot")]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=values,
        mode="lines+markers",
        name="VDOT",
        line=dict(color=PURPLE, width=3),
        fill="tozeroy",
        fillcolor=PURPLE_FILL,
        marker=dict(size=8, color=PURPLE),
    ))
    layout = _base_layout("VDOT 추이", height=220)
    layout["yaxis"]["title"] = "VDOT"
    fig.update_layout(**layout)
    return fig


def weekly_plan_vs_actual_chart(
    plan: dict | None,
    actual_by_day: dict,  # {"mon": km, ...}
    dates: dict,          # {"mon": "2026-05-25", ...}
) -> go.Figure:
    """이번 주 계획 vs 실제 막대 차트"""
    day_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    day_kr   = ["월", "화", "수", "목", "금", "토", "일"]

    sessions = plan.get("sessions", {}) if plan else {}
    labels = []
    plan_km = []
    actual_km = []

    for key, kr in zip(day_keys, day_kr):
        date_str = dates.get(key, "")
        date_display = date_str[5:].replace("-", "/") if date_str else ""
        labels.append(f"{kr}<br><sub>{date_display}</sub>")
        s = sessions.get(key, {})
        plan_km.append(s.get("distance_km", 0) if s.get("type", "휴식") != "휴식" else 0)
        actual_km.append(actual_by_day.get(key, 0))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="계획",
        x=labels, y=plan_km,
        marker_color="rgba(113,50,245,0.25)",
        width=0.35, offset=-0.18,
    ))
    fig.add_trace(go.Bar(
        name="실제",
        x=labels, y=actual_km,
        marker_color=PURPLE,
        width=0.35, offset=0.18,
    ))
    layout = _base_layout("이번 주 계획 vs 실제", height=260)
    layout["barmode"] = "overlay"
    layout["yaxis"]["title"] = "km"
    layout["yaxis"]["rangemode"] = "tozero"
    fig.update_layout(**layout)
    return fig


def score_gauge_chart(value: int, label: str, color: str = PURPLE) -> go.Figure:
    """보조 지표 게이지"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=1),
            bar=dict(color=color),
            bgcolor="white",
            borderwidth=1,
            bordercolor=GRID_COLOR,
            steps=[
                dict(range=[0, 40],  color="rgba(239,68,68,0.1)"),
                dict(range=[40, 70], color="rgba(251,191,36,0.1)"),
                dict(range=[70, 100],color="rgba(20,158,97,0.1)"),
            ],
        ),
        title=dict(text=label, font=dict(size=14)),
        number=dict(suffix="", font=dict(size=28, color=color)),
    ))
    fig.update_layout(height=180, margin=dict(l=20, r=20, t=40, b=10),
                      paper_bgcolor="white")
    return fig


def weekly_km_bar_chart(labels: list, values: list) -> go.Figure:
    """주간 마일리지 바 차트"""
    avg = round(sum(values) / len(values), 1) if values else 0
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=values,
        name="주간 km",
        marker_color=PURPLE,
        marker_opacity=0.75,
    ))
    # add_hline: 전체 너비에 걸쳐 평균선 표시
    fig.add_hline(
        y=avg,
        line_dash="dash",
        line_color=RED,
        line_width=2,
        annotation_text=f"평균 {avg}km",
        annotation_position="top right",
        annotation_font_color=RED,
    )
    layout = _base_layout("주간 마일리지", height=260)
    layout["yaxis"]["title"] = "km"
    layout["yaxis"]["rangemode"] = "tozero"
    layout["showlegend"] = False
    fig.update_layout(**layout)
    return fig


def pace_trend_chart(activities: list[dict]) -> go.Figure:
    """페이스 트렌드 (낮을수록 빠름, y축 역순)"""
    if not activities:
        return go.Figure()

    labels = [a["date"][:10][5:] for a in activities]
    paces  = [round(a["avg_pace_sec"] / 60, 2) for a in activities if a.get("avg_pace_sec")]

    if not paces:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=paces,
        mode="lines+markers",
        name="페이스 (분/km)",
        line=dict(color=GREEN, width=2),
        fill="tozeroy",
        fillcolor="rgba(20,158,97,0.08)",
        marker=dict(size=6, color=GREEN),
    ))
    layout = _base_layout("페이스 트렌드", height=240)
    layout["yaxis"]["autorange"] = "reversed"
    layout["yaxis"]["title"] = "분/km (낮을수록 빠름)"
    layout["yaxis"]["tickformat"] = ".2f"
    fig.update_layout(**layout)
    return fig


def hr_trend_chart(activities: list[dict], zones: dict) -> go.Figure:
    """심박 트렌드 + 존 경계선"""
    if not activities:
        return go.Figure()

    labels = [a["date"][:10][5:] for a in activities]
    hrs    = [a.get("avg_heartrate") for a in activities]

    z2 = zones.get("zone2_max", 150)
    z3 = zones.get("zone3_max", 162)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=hrs,
        mode="lines+markers",
        name="평균 심박",
        line=dict(color=RED, width=2),
        fill="tozeroy",
        fillcolor="rgba(239,68,68,0.08)",
        marker=dict(size=6, color=RED),
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=[z2] * len(labels),
        mode="lines", name=f"존2 상한 ({z2}bpm)",
        line=dict(color=YELLOW, dash="dash", width=1.5),
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=[z3] * len(labels),
        mode="lines", name=f"존3 상한 ({z3}bpm)",
        line=dict(color=RED, dash="dash", width=1.5),
    ))
    layout = _base_layout("심박 트렌드", height=240)
    layout["yaxis"]["title"] = "bpm"
    valid = [h for h in hrs if h]
    if valid:
        layout["yaxis"]["range"] = [min(valid) - 10, max(valid) + 10]
    fig.update_layout(**layout)
    return fig


def monthly_weekly_km_chart(labels: list, values: list) -> go.Figure:
    """월간 주차별 마일리지"""
    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=PURPLE,
        marker_opacity=0.75,
        text=[f"{v}km" for v in values],
        textposition="outside",
    ))
    layout = _base_layout("주차별 마일리지", height=240)
    layout["yaxis"]["title"] = "km"
    layout["yaxis"]["rangemode"] = "tozero"
    layout["showlegend"] = False
    fig.update_layout(**layout)
    return fig
