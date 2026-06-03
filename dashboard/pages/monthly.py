"""Page — 월간 트래킹"""

import streamlit as st
import json
from datetime import datetime

from dashboard.db import (
    get_available_months, get_monthly_report,
    get_monthly_weekly_km, get_monthly_activities_detail,
    get_score_history, get_zones,
)
from dashboard.components.styles import inject_css, card
from dashboard.components.charts import (
    monthly_weekly_km_chart, pace_trend_chart, hr_trend_chart, vdot_trend_chart,
)

inject_css()

# ── 월 선택 ──────────────────────────────────────────────────────────────────
months = get_available_months()
if not months:
    st.info("아직 데이터가 없습니다.")
    st.stop()

st.markdown('<div class="kr-section-title">📈 월간 트래킹</div>', unsafe_allow_html=True)

# ── VDOT 추이 (레이스/트라이얼 기준, 6~8주마다 업데이트) ─────────────────────
score_hist_all = get_score_history(weeks=52)
if score_hist_all:
    st.plotly_chart(vdot_trend_chart(score_hist_all), width="stretch")
    st.markdown(
        '<div class="kr-sub" style="text-align:right;margin-top:-12px">'
        '📌 레이스/타임 트라이얼 후 설정 페이지에서 PB 업데이트 시 반영됩니다.</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        card('<div class="kr-sub">📌 VDOT 데이터 축적 중 — 매주 월요일 스냅샷이 저장됩니다.</div>'),
        unsafe_allow_html=True,
    )

st.markdown("---")
selected = st.selectbox("월 선택", months, index=0)
st.markdown("---")

# ── 데이터 로드 ──────────────────────────────────────────────────────────────
report   = get_monthly_report(selected)
wk_labels, wk_km = get_monthly_weekly_km(selected)
acts     = get_monthly_activities_detail(selected)
zones    = get_zones()

# 선택 월 VDOT 변화 (score_hist_all 재사용)
month_scores = [s for s in score_hist_all if s["week_start"].startswith(selected)]

# ── 월간 요약 카드 ─────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)

with c1:
    if report:
        total_km = report.get("total_km", 0)
        sessions = report.get("total_sessions", 0)
        st.metric("총 거리", f"{total_km}km", f"{sessions}회 운동")
    elif acts:
        total_km = round(sum(a["distance_km"] for a in acts), 1)
        st.metric("총 거리", f"{total_km}km", f"{len(acts)}회 운동")
    else:
        st.metric("총 거리", "-")

with c2:
    if report:
        adh = report.get("adherence_rate", 0)
        color = "normal" if adh >= 80 else "inverse"
        st.metric("이행률", f"{adh}%")
    else:
        st.metric("이행률", "-", help="주간 계획 데이터가 있을 때 계산됩니다")

with c3:
    if len(month_scores) >= 2:
        v_start = month_scores[0].get("vdot")
        v_end   = month_scores[-1].get("vdot")
        if v_start and v_end:
            delta = round(v_end - v_start, 1)
            delta_str = f"+{delta}" if delta >= 0 else str(delta)
            st.metric("VDOT 변화", f"{v_end}", delta_str)
        else:
            st.metric("VDOT", "-")
    elif month_scores:
        v = month_scores[0].get("vdot")
        st.metric("VDOT", str(v) if v else "-")
    else:
        st.metric("VDOT", "-", help="매주 월요일 스냅샷이 저장됩니다")

st.markdown("<br>", unsafe_allow_html=True)

# ── 주차별 마일리지 ───────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">📊 주차별 마일리지</div>', unsafe_allow_html=True)
if wk_km:
    st.plotly_chart(monthly_weekly_km_chart(wk_labels, wk_km), width="stretch")
else:
    st.info("운동 데이터가 없습니다.")

# ── 페이스 & 심박 트렌드 (2컬럼) ─────────────────────────────────────────────
st.markdown('<div class="kr-section-title">📉 트렌드</div>', unsafe_allow_html=True)
t1, t2 = st.columns(2)
with t1:
    if acts:
        st.plotly_chart(pace_trend_chart(acts), width="stretch")
    else:
        st.info("데이터 없음")
with t2:
    if acts:
        st.plotly_chart(hr_trend_chart(acts, zones), width="stretch")
    else:
        st.info("데이터 없음")

# ── 존 분포 ──────────────────────────────────────────────────────────────────
if report and report.get("zone_distribution"):
    st.markdown('<div class="kr-section-title">💓 존 분포</div>', unsafe_allow_html=True)
    try:
        zone_dist = json.loads(report["zone_distribution"])
        zone_cols = st.columns(len(zone_dist))
        zone_colors = ["gray", "green", "yellow", "yellow", "red"]
        for i, (zone, pct) in enumerate(zone_dist.items()):
            with zone_cols[i]:
                color = zone_colors[i] if i < len(zone_colors) else "gray"
                st.markdown(
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:24px;font-weight:700;color:#101114'>{pct}%</div>"
                    f"<div class='kr-sub'>{zone}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
    except Exception:
        pass

# ── AI 평가 ──────────────────────────────────────────────────────────────────
if report:
    st.markdown('<div class="kr-section-title">🤖 AI 평가</div>', unsafe_allow_html=True)
    a1, a2 = st.columns(2)
    with a1:
        fitness = report.get("fitness_assessment", "")
        if fitness:
            st.markdown(card(
                f"<b>📝 피트니스 평가</b><br><br>{fitness}",
                border="purple"
            ), unsafe_allow_html=True)
    with a2:
        goal_prog = report.get("goal_progress", "")
        if goal_prog:
            st.markdown(card(
                f"<b>🎯 목표 진행 상황</b><br><br>{goal_prog}",
                border="green"
            ), unsafe_allow_html=True)

    next_focus = report.get("next_month_focus", "")
    if next_focus:
        st.markdown(card(
            f"<b>➡️ 다음 달 핵심 포인트</b><br><br>{next_focus}",
            border="yellow"
        ), unsafe_allow_html=True)
else:
    st.markdown(
        card('<div class="kr-sub">📌 월간 리포트가 없습니다. (매월 1일 자동 생성)</div>'),
        unsafe_allow_html=True,
    )

# ── 활동 목록 ─────────────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">🏃 활동 목록</div>', unsafe_allow_html=True)
if acts:
    table_rows = ""
    for a in reversed(acts):
        date_str = a["date"][:10]
        dist     = round(a["distance_km"], 2)
        pace_sec = a.get("avg_pace_sec", 0)
        pace_str = f"{int(pace_sec//60)}:{int(pace_sec%60):02d}/km" if pace_sec else "-"
        hr_str   = f"{round(a.get('avg_heartrate',0))}bpm" if a.get("avg_heartrate") else "-"
        t_type   = a.get("training_type") or "-"
        table_rows += (
            f"<tr>"
            f"<td>{date_str}</td>"
            f"<td>{dist}km</td>"
            f"<td>{pace_str}</td>"
            f"<td>{hr_str}</td>"
            f"<td>{t_type}</td>"
            f"</tr>"
        )

    st.markdown(
        '<div class="kr-card"><table class="kr-table">'
        '<thead><tr>'
        '<th>날짜</th><th>거리</th><th>페이스</th><th>심박</th><th>종류</th>'
        f'</tr></thead><tbody>{table_rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )
