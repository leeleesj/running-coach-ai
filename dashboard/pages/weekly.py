"""Page — 이번 주"""

import streamlit as st
import json
from datetime import datetime

from dashboard.db import (
    get_current_week_range, get_week_activities, get_current_week_plan,
    get_week_compliance, get_acwr,
)
from dashboard.components.styles import inject_css, badge, card

inject_css()

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_KR   = ["월", "화", "수", "목", "금", "토", "일"]

# ── 데이터 로드 ──────────────────────────────────────────────────────────────
week_start, week_end = get_current_week_range()
plan       = get_current_week_plan()
week_acts  = get_week_activities(week_start)
compliance = get_week_compliance(week_start)
acwr_data  = get_acwr()

st.markdown('<div class="kr-section-title">📋 이번 주 훈련</div>', unsafe_allow_html=True)
st.markdown(f'<div class="kr-sub">{week_start} ~ {week_end}</div>', unsafe_allow_html=True)
st.markdown("---")

# ── 주간 누적 현황 ─────────────────────────────────────────────────────────────
actual_km    = round(sum(a["distance_km"] for a in week_acts), 1)
planned_km   = plan.get("total_planned_km", 0) if plan else 0
avg_hr       = (sum(a["avg_heartrate"] for a in week_acts if a.get("avg_heartrate")) /
                max(len([a for a in week_acts if a.get("avg_heartrate")]), 1))
sessions_cnt = len(week_acts)

c1, c2, c3, c4 = st.columns(4)
with c1:
    pct = min(int(actual_km / planned_km * 100), 100) if planned_km else 0
    st.metric("누적 거리", f"{actual_km}km", f"계획 {planned_km}km")
    st.progress(pct / 100)
with c2:
    st.metric("완료 세션", f"{sessions_cnt}회")
with c3:
    st.metric("평균 심박", f"{round(avg_hr, 0):.0f}bpm" if avg_hr else "-")
with c4:
    acwr = acwr_data.get("acwr", "-")
    st.metric("ACWR", acwr, help="0.8~1.3이 안전 범위")

st.markdown("<br>", unsafe_allow_html=True)

# ── 훈련 계획 테이블 ───────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">📅 훈련 계획</div>', unsafe_allow_html=True)

if not plan:
    st.info("이번 주 훈련 계획이 없습니다. (매주 월요일 07:00 자동 생성)")
else:
    sessions = plan.get("sessions", {})
    dates    = plan.get("dates", {})
    phase_kr = {"base":"베이스","build":"빌드","peak":"피크","taper":"테이퍼"}.get(plan.get("phase",""), "")

    st.markdown(
        f'{badge(phase_kr, "purple")} '
        f'{badge(f"목표 {planned_km}km", "gray")}',
        unsafe_allow_html=True,
    )
    if plan.get("weekly_comment"):
        st.markdown(
            f"<div class='kr-sub' style='margin-top:8px'>{plan['weekly_comment']}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<br>", unsafe_allow_html=True)

    # 요일별 실제 활동 매핑
    actual_by_day: dict[str, list] = {k: [] for k in DAY_KEYS}
    for act in week_acts:
        act_date = act["date"][:10]
        for key in DAY_KEYS:
            if dates.get(key, "")[:10] == act_date:
                actual_by_day[key].append(act)

    # 테이블 렌더링
    table_rows = ""
    for key, kr in zip(DAY_KEYS, DAY_KR):
        s        = sessions.get(key, {})
        date_str = dates.get(key, "")[:10]
        s_type   = s.get("type", "휴식")
        p_km     = s.get("distance_km", 0) if s_type != "휴식" else 0
        p_pace   = s.get("pace", "-")
        p_hr     = s.get("heartrate", "-")
        acts     = actual_by_day.get(key, [])
        a_km     = round(sum(a["distance_km"] for a in acts), 1)
        a_hr     = round(sum(a["avg_heartrate"] for a in acts if a.get("avg_heartrate")) /
                         max(len([a for a in acts if a.get("avg_heartrate")]), 1), 0) if acts else 0

        # 상태 뱃지
        if s_type == "휴식":
            status = badge("휴식", "gray")
        elif not acts:
            today = datetime.now().strftime("%Y-%m-%d")
            status = badge("예정", "gray") if date_str >= today else badge("미완", "red")
        elif a_km >= p_km * 0.8:
            status = badge("✅ 완료", "green")
        else:
            status = badge("⚠️ 부분", "yellow")

        a_km_str = f"{a_km}km" if acts else "-"
        a_hr_str = f"{int(a_hr)}bpm" if a_hr else "-"

        table_rows += (
            f"<tr>"
            f"<td><b>{kr}</b><br><span class='kr-sub'>{date_str[5:] if date_str else ''}</span></td>"
            f"<td>{s_type}</td>"
            f"<td>{p_km}km</td>"
            f"<td>{p_pace}</td>"
            f"<td>{a_km_str}</td>"
            f"<td>{a_hr_str}</td>"
            f"<td>{status}</td>"
            f"</tr>"
        )

    st.markdown(
        '<div class="kr-card"><table class="kr-table">'
        '<thead><tr>'
        '<th>요일</th><th>계획 종류</th><th>계획 거리</th><th>목표 페이스</th>'
        '<th>실제 거리</th><th>실제 심박</th><th>상태</th>'
        f'</tr></thead><tbody>{table_rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )

# ── Daily 피드백 (expander) ───────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">💬 운동 피드백</div>', unsafe_allow_html=True)

if not week_acts:
    st.markdown(card('<div class="kr-sub">이번 주 완료된 운동이 없습니다.</div>'), unsafe_allow_html=True)
else:
    for act in sorted(week_acts, key=lambda x: x["date"], reverse=True):
        date_str = act["date"][:10]
        name     = act.get("name") or "러닝"
        dist     = round(act["distance_km"], 2)
        pace_sec = act.get("avg_pace_sec", 0)
        pace_str = f"{int(pace_sec//60)}:{int(pace_sec%60):02d}/km" if pace_sec else "-"
        hr_str   = f"{round(act.get('avg_heartrate',0))}bpm" if act.get("avg_heartrate") else "-"

        analysis = {}
        if act.get("ai_analysis_json"):
            try:
                analysis = json.loads(act["ai_analysis_json"])
            except Exception:
                pass

        label = f"{date_str} — {name} ({dist}km | {pace_str} | {hr_str})"
        with st.expander(label):
            if analysis:
                comment = analysis.get("comment", "") or analysis.get("feedback", "")
                plan_vs = analysis.get("plan_vs_actual", "")
                tomorrow = analysis.get("tomorrow", "")

                if comment:
                    st.markdown(card(f"<b>🤖 AI 분석</b><br>{comment}", "purple"), unsafe_allow_html=True)
                if plan_vs:
                    st.info(f"계획 대비: {plan_vs}")
                if tomorrow:
                    st.success(f"내일 제안: {tomorrow}")
            else:
                st.markdown(card(
                    f'<div class="kr-sub">AI 분석 없음 (Strava Webhook 수신 전 데이터)</div>'
                ), unsafe_allow_html=True)

            # 기본 수치 요약
            st.markdown(
                f"<div class='kr-sub' style='margin-top:8px'>"
                f"거리 {dist}km &nbsp;|&nbsp; 페이스 {pace_str} &nbsp;|&nbsp;"
                f"심박 {hr_str} &nbsp;|&nbsp; 종류 {act.get('training_type') or '-'}"
                f"</div>",
                unsafe_allow_html=True,
            )
