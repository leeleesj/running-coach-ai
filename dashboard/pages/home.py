"""Page 1 — 홈"""

import streamlit as st
import json
from datetime import datetime, timedelta

from dashboard.db import (
    get_vdot_info, get_acwr, get_zones,
    get_current_week_range, get_week_activities, get_current_week_plan,
    get_week_compliance, get_score_history, get_weekly_km_history,
)
from dashboard.components.styles import inject_css, stat_card, badge, card
from dashboard.components.charts import (
    weekly_plan_vs_actual_chart,
    score_gauge_chart, weekly_km_bar_chart,
)

st.set_page_config(page_title="홈 — Running Coach", page_icon="🏠", layout="wide")
inject_css()

# ── 데이터 로드 ──────────────────────────────────────────────────────────────
vdot_info  = get_vdot_info()
acwr_data  = get_acwr()
zones      = get_zones()
week_start, week_end = get_current_week_range()
week_acts  = get_week_activities(week_start)
plan       = get_current_week_plan()
compliance = get_week_compliance(week_start)
score_hist = get_score_history(weeks=12)
week_labels, week_km = get_weekly_km_history(weeks=10)

# ── 헤더 ─────────────────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">🏃 Running Coach</div>', unsafe_allow_html=True)
st.markdown(f'<div class="kr-sub">업데이트: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>',
            unsafe_allow_html=True)
st.markdown("---")

# ── 상단 3열 카드 ─────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    vdot_val = vdot_info.get("vdot_pb", "-")
    vdot_gap = vdot_info.get("vdot_gap")
    sub = f"목표 VDOT {vdot_info.get('vdot_goal')} (+{vdot_gap}p 필요)" if vdot_gap else ""
    st.markdown(stat_card(
        value=str(vdot_val) if vdot_val else "-",
        label=f"VDOT ({vdot_info.get('vdot_level', '-')})",
        sub=sub,
    ), unsafe_allow_html=True)

with col2:
    days_left = vdot_info.get("days_left")
    d_val = f"D-{days_left}" if days_left and days_left > 0 else "미정"
    race_sub = f"{vdot_info.get('event', '')} {vdot_info.get('target_str', '')}"
    st.markdown(stat_card(
        value=d_val,
        label="목표 대회",
        sub=race_sub,
    ), unsafe_allow_html=True)

with col3:
    actual_km = sum(a["distance_km"] for a in week_acts)
    planned_km = plan.get("total_planned_km", 0) if plan else 0
    comp_sub = f"실제 {round(actual_km,1)}km / 계획 {planned_km}km"
    comp_color = "green" if compliance >= 80 else "red" if compliance < 50 else ""
    st.markdown(stat_card(
        value=f"{compliance}%",
        label="이번 주 이행도",
        sub=comp_sub,
        sub_color=comp_color,
    ), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── ACWR 경고 배너 ────────────────────────────────────────────────────────────
try:
    acwr_val = float(acwr_data.get("acwr", 0))
    acute_km = float(acwr_data.get("acute_km", 0))
    chronic_km = float(acwr_data.get("chronic_weekly_km", 0))
    # 데이터가 없으면 배너 표시 안 함
    if acute_km > 0 or chronic_km > 0:
        if acwr_val > 1.3:
            st.error(f"⚡ ACWR {acwr_val} — 부상 위험 구간 (안전: 0.8~1.3) | "
                     f"최근 7일 {acute_km}km / 4주 평균 {chronic_km}km/주")
        elif acwr_val > 1.1:
            st.warning(f"⚡ ACWR {acwr_val} — 주의 구간 | "
                       f"최근 7일 {acute_km}km / 4주 평균 {chronic_km}km/주")
        else:
            st.success(f"⚡ ACWR {acwr_val} — 안전 구간 | "
                       f"최근 7일 {acute_km}km / 4주 평균 {chronic_km}km/주")
except (ValueError, TypeError):
    pass

# ── 이번 주 계획 vs 실제 / 주간 마일리지 (2컬럼) ─────────────────────────────
left_col, right_col = st.columns(2)

with left_col:
    st.markdown('<div class="kr-section-title">📅 이번 주 계획 vs 실제</div>', unsafe_allow_html=True)
    if plan:
        # 요일별 실제 km 집계
        day_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        dates    = plan.get("dates", {})
        actual_by_day: dict[str, float] = {k: 0.0 for k in day_keys}

        for act in week_acts:
            act_date = act["date"][:10]
            for key in day_keys:
                if dates.get(key, "")[:10] == act_date:
                    actual_by_day[key] += act["distance_km"]

        st.plotly_chart(
            weekly_plan_vs_actual_chart(plan, actual_by_day, dates),
            use_container_width=True,
        )

        # 요일별 상태 요약
        sessions = plan.get("sessions", {})
        day_cols = st.columns(7)
        for i, (key, kr) in enumerate(zip(day_keys, ["월","화","수","목","금","토","일"])):
            s = sessions.get(key, {})
            p_km = s.get("distance_km", 0) if s.get("type", "휴식") != "휴식" else 0
            a_km = actual_by_day.get(key, 0)
            date_str = dates.get(key, "")

            with day_cols[i]:
                if p_km == 0:
                    status = badge("휴식", "gray")
                elif a_km == 0:
                    status = badge("예정", "gray")
                elif a_km >= p_km * 0.8:
                    status = badge("✅", "green")
                else:
                    status = badge("⚠️", "yellow")
                st.markdown(
                    f"<div style='text-align:center'>"
                    f"<div class='kr-sub'>{kr} {date_str[5:] if date_str else ''}</div>"
                    f"<div style='font-size:13px'>{p_km}km 계획</div>"
                    f"<div style='font-size:13px'>{round(a_km,1)}km 실제</div>"
                    f"{status}</div>",
                    unsafe_allow_html=True,
                )
    else:
        st.info("이번 주 훈련 계획이 없습니다. (매주 월요일 07:00 자동 생성)")

with right_col:
    st.markdown('<div class="kr-section-title">📊 주간 마일리지</div>', unsafe_allow_html=True)
    if week_labels:
        st.plotly_chart(weekly_km_bar_chart(week_labels, week_km), use_container_width=True)
    else:
        st.info("데이터 없음")

# ── 보조 지표 ─────────────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">🔬 보조 지표</div>', unsafe_allow_html=True)
latest_score = score_hist[-1] if score_hist else None
g1, g2, g3 = st.columns(3)
with g1:
    v = latest_score["fitness_score"] if latest_score else 0
    st.plotly_chart(score_gauge_chart(v, "체력 지수 (CTL)"), use_container_width=True)
with g2:
    v = latest_score["efficiency_score"] if latest_score else 0
    st.plotly_chart(score_gauge_chart(v, "효율 지수 (심박)"), use_container_width=True)
with g3:
    v = latest_score["compliance_score"] if latest_score else int(compliance)
    st.plotly_chart(score_gauge_chart(v, "이행 지수"), use_container_width=True)

# ── VDOT 훈련 페이스 참고 ────────────────────────────────────────────────────
paces = vdot_info.get("paces", {})
preds = vdot_info.get("predictions", {})
if paces:
    st.markdown('<div class="kr-section-title">📐 훈련 페이스 처방</div>', unsafe_allow_html=True)
    p1, p2 = st.columns(2)
    with p1:
        st.markdown(card(f"""
        <div class="kr-sub">현재 PB 기준 페이스 (VDOT {vdot_info.get('vdot_pb')})</div><br>
        <b>존2 조깅 (E)</b>: {paces.get('E', {}).get('pace_range', '-')}<br>
        <b>템포런 (T)</b>: {paces.get('T', {}).get('pace_range', '-')}<br>
        <b>인터벌 (I)</b>: {paces.get('I', {}).get('pace_range', '-')}
        """), unsafe_allow_html=True)
    with p2:
        st.markdown(card(f"""
        <div class="kr-sub">현재 기준 예상 기록</div><br>
        <b>5km</b>: {preds.get('5km', '-')}<br>
        <b>10km</b>: {preds.get('10km', '-')}<br>
        <b>하프</b>: {preds.get('half', '-')}
        """), unsafe_allow_html=True)
