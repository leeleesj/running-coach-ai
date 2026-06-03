"""Page — 설정 (목표 직접 입력)"""

import streamlit as st
from datetime import datetime, date

from app.models.database import get_active_goals, upsert_goal, get_training_zones, get_connection
from dashboard.components.styles import inject_css, card, badge

inject_css()


def _parse_time(s: str) -> int | None:
    """'55:00' 또는 '1:03:00' → 초"""
    s = s.strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        return None


def _fmt_time(sec: int | None) -> str:
    """초 → 'MM:SS' 또는 'H:MM:SS'"""
    if not sec:
        return ""
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


st.markdown('<div class="kr-section-title">⚙️ 설정</div>', unsafe_allow_html=True)
st.markdown("---")

# ── 목표 관리 ─────────────────────────────────────────────────────────────────
st.markdown('<div class="kr-section-title">🎯 훈련 목표</div>', unsafe_allow_html=True)

goals = get_active_goals(1)
primary = next((g for g in goals if g["priority"] == "primary"), None)

with st.form("goal_form"):
    st.markdown("**주요 목표**")

    col1, col2 = st.columns(2)
    with col1:
        event_type = st.selectbox(
            "목표 종목",
            ["10km", "5km", "half", "full"],
            index=["10km", "5km", "half", "full"].index(primary["event_type"])
            if primary else 0,
        )
        target_time_str = st.text_input(
            "목표 기록 (MM:SS 또는 H:MM:SS)",
            value=_fmt_time(primary.get("target_time_sec")) if primary else "",
            placeholder="예: 55:00",
        )
        pb_time_str = st.text_input(
            "현재 PB (MM:SS 또는 H:MM:SS)",
            value=_fmt_time(primary.get("pb_time_sec")) if primary else "",
            placeholder="예: 1:03:00",
            help="훈련 페이스 처방 기준. 미입력 시 목표 기록으로 대체.",
        )

    with col2:
        race_name = st.text_input(
            "대회명",
            value=primary.get("race_name") or "" if primary else "",
            placeholder="예: 춘천마라톤",
        )
        target_date_val = None
        if primary and primary.get("target_date"):
            try:
                target_date_val = datetime.fromisoformat(primary["target_date"]).date()
            except Exception:
                pass
        target_date = st.date_input(
            "목표 대회 날짜",
            value=target_date_val,
            min_value=date.today(),
        )
        race_confirmed = st.checkbox(
            "대회 등록 완료",
            value=bool(primary.get("race_confirmed")) if primary else False,
        )

    st.markdown("**훈련 제약**")
    col3, col4 = st.columns(2)
    with col3:
        weekly_days = st.slider(
            "주당 훈련 가능 일수",
            min_value=2, max_value=7,
            value=primary.get("weekly_days_available", 4) if primary else 4,
        )
    with col4:
        max_km = st.number_input(
            "주당 최대 거리 (km)",
            min_value=10.0, max_value=120.0, step=5.0,
            value=float(primary.get("max_weekly_km", 30)) if primary else 30.0,
        )

    injury_notes = st.text_area(
        "부상 메모",
        value=primary.get("injury_notes") or "" if primary else "",
        placeholder="예: 왼쪽 무릎 통증, 5월 말 복귀 예정",
        height=80,
    )

    submitted = st.form_submit_button("💾 저장", type="primary", use_container_width=True)

if submitted:
    target_sec = _parse_time(target_time_str)
    pb_sec     = _parse_time(pb_time_str)

    if not target_sec:
        st.error("목표 기록 형식을 확인하세요. (예: 55:00 또는 1:03:00)")
    else:
        target_date_str = target_date.isoformat() if target_date else None
        upsert_goal(
            user_id=1,
            priority="primary",
            event_type=event_type,
            target_time_sec=target_sec,
            pb_time_sec=pb_sec,
            target_date=target_date_str,
            race_name=race_name or None,
            race_confirmed=race_confirmed,
            weekly_days_available=weekly_days,
            max_weekly_km=float(max_km),
            injury_notes=injury_notes or None,
        )
        st.success("✅ 목표가 저장되었습니다!")
        st.rerun()

# ── 현재 저장된 목표 미리보기 ─────────────────────────────────────────────────
if primary:
    from app.utils.vdot import calc_vdot_from_goal, vdot_level, _fmt_time as vdot_fmt
    pb_sec_val = primary.get("pb_time_sec")
    target_sec_val = primary.get("target_time_sec")
    vdot_pb   = calc_vdot_from_goal(primary["event_type"], pb_sec_val) if pb_sec_val else None
    vdot_goal = calc_vdot_from_goal(primary["event_type"], target_sec_val) if target_sec_val else None

    st.markdown("<br>", unsafe_allow_html=True)
    goal_line = (
        f"{badge(primary['event_type'], 'purple')}"
        f"&nbsp;목표: <b>{vdot_fmt(target_sec_val)}</b>"
        + (f"&nbsp;→ VDOT {vdot_goal} ({vdot_level(vdot_goal)})" if vdot_goal else "")
        + f"<br>&nbsp;&nbsp;&nbsp;&nbsp;PB: <b>{vdot_fmt(pb_sec_val) if pb_sec_val else '미입력'}</b>"
        + (f"&nbsp;→ VDOT {vdot_pb} ({vdot_level(vdot_pb)})" if vdot_pb else "")
        + "<br>"
        + (f"&nbsp;&nbsp;&nbsp;&nbsp;대회: {primary.get('race_name') or ''} {primary.get('target_date', '')[:10]}"
           if primary.get('target_date') else "&nbsp;&nbsp;&nbsp;&nbsp;대회 날짜: 미정")
        + f"<br>&nbsp;&nbsp;&nbsp;&nbsp;훈련: 주 {primary.get('weekly_days_available')}일 / 최대 {primary.get('max_weekly_km')}km"
        + (f"<br>&nbsp;&nbsp;&nbsp;&nbsp;부상: {primary['injury_notes']}" if primary.get('injury_notes') else "")
    )
    st.markdown(card(
        f"<b>현재 저장된 목표</b><br><br>{goal_line}",
        border="purple",
    ), unsafe_allow_html=True)

# ── 심박존 설정 ───────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="kr-section-title">💓 심박존 설정</div>', unsafe_allow_html=True)

zones = get_training_zones(1)
with st.form("zone_form"):
    z1, z2, z3, z4 = st.columns(4)
    with z1:
        zone1 = st.number_input("존1 상한 (bpm)", value=zones["zone1_max"], step=1)
    with z2:
        zone2 = st.number_input("존2 상한 (bpm)", value=zones["zone2_max"], step=1)
    with z3:
        zone3 = st.number_input("존3 상한 (bpm)", value=zones["zone3_max"], step=1)
    with z4:
        zone4 = st.number_input("존4 상한 (bpm)", value=zones["zone4_max"], step=1)
    max_hr = st.number_input("최대 심박 (bpm)", value=zones["max_heartrate"], step=1)

    zone_submitted = st.form_submit_button("💾 심박존 저장", use_container_width=True)

if zone_submitted:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO training_zones (user_id, zone1_max, zone2_max, zone3_max, zone4_max, max_heartrate)
        VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            zone1_max=excluded.zone1_max, zone2_max=excluded.zone2_max,
            zone3_max=excluded.zone3_max, zone4_max=excluded.zone4_max,
            max_heartrate=excluded.max_heartrate, updated_at=datetime('now')
    """, (int(zone1), int(zone2), int(zone3), int(zone4), int(max_hr)))
    conn.commit()
    conn.close()
    st.success("✅ 심박존이 저장되었습니다!")
    st.rerun()

st.markdown(card(
    f"<b>현재 심박존</b><br><br>"
    f"존1: ~{zones['zone1_max']}bpm &nbsp;|&nbsp; "
    f"존2: {zones['zone1_max']+1}~{zones['zone2_max']}bpm &nbsp;|&nbsp; "
    f"존3: {zones['zone2_max']+1}~{zones['zone3_max']}bpm &nbsp;|&nbsp; "
    f"존4: {zones['zone3_max']+1}~{zones['zone4_max']}bpm &nbsp;|&nbsp; "
    f"존5: {zones['zone4_max']+1}~bpm<br>"
    f"최대 심박: {zones['max_heartrate']}bpm"
), unsafe_allow_html=True)

# ── 주간 계획 재생성 ───────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="kr-section-title">📅 주간 계획</div>', unsafe_allow_html=True)
st.markdown(
    "<div class='kr-sub'>목표나 부상 메모 변경 후 이번 주 계획을 즉시 재생성합니다.<br>"
    "기존 계획은 덮어씁니다.</div>",
    unsafe_allow_html=True,
)
st.markdown("<br>", unsafe_allow_html=True)

if st.button("🔄 이번 주 계획 재생성", type="primary", use_container_width=True):
    import requests
    try:
        # 기존 계획 삭제 후 재생성
        from app.models.database import get_connection as _gc
        from datetime import datetime, timedelta
        _now = datetime.now()
        _monday = (_now - timedelta(days=_now.weekday())).strftime("%Y-%m-%d")
        _conn = _gc()
        _conn.execute("DELETE FROM weekly_plans WHERE week_start = ? AND user_id = 1", (_monday,))
        _conn.commit()
        _conn.close()

        with st.spinner("Qwen이 계획을 생성 중입니다... (약 1~2분)"):
            resp = requests.get("http://localhost:8000/test/weekly-coach", timeout=180)
        if resp.status_code == 200 and "plan" in resp.json():
            st.success("✅ 이번 주 계획이 재생성되었습니다!")
            st.rerun()
        else:
            st.error(f"생성 실패: {resp.text[:200]}")
    except Exception as e:
        st.error(f"오류: {e}")
