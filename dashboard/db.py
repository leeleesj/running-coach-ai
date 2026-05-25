"""
대시보드 전용 데이터 접근 레이어

app/models/database.py의 get_connection()을 재사용하고
대시보드에서 필요한 집계 쿼리를 제공한다.
"""

import json
from datetime import datetime, timedelta
from app.models.database import get_connection, get_active_goals, get_training_zones, calculate_acwr
from app.utils.vdot import calc_vdot_from_goal, get_training_paces, predict_all_races, vdot_level, _fmt_time


# ── 목표 & VDOT ──────────────────────────────────────────────────────────────

def get_vdot_info(user_id: int = 1) -> dict:
    """현재 목표 기반 VDOT 정보"""
    goals = get_active_goals(user_id)
    if not goals:
        return {}

    primary = next((g for g in goals if g["priority"] == "primary"), goals[0])
    pb_sec = primary.get("pb_time_sec") or primary.get("target_time_sec", 0)
    target_sec = primary.get("target_time_sec", 0)
    event = primary.get("event_type", "10km")

    vdot_pb = calc_vdot_from_goal(event, pb_sec) if pb_sec else None
    vdot_goal = calc_vdot_from_goal(event, target_sec) if target_sec else None
    paces = get_training_paces(vdot_pb) if vdot_pb else {}
    preds = predict_all_races(vdot_pb) if vdot_pb else {}

    days_left = None
    if primary.get("target_date"):
        target_dt = datetime.fromisoformat(primary["target_date"])
        days_left = (target_dt - datetime.now()).days

    return {
        "event": event,
        "pb_sec": pb_sec,
        "pb_str": _fmt_time(pb_sec) if pb_sec else "미입력",
        "target_sec": target_sec,
        "target_str": _fmt_time(target_sec) if target_sec else "미설정",
        "vdot_pb": vdot_pb,
        "vdot_goal": vdot_goal,
        "vdot_level": vdot_level(vdot_pb) if vdot_pb else "-",
        "vdot_gap": round(vdot_goal - vdot_pb, 1) if (vdot_pb and vdot_goal) else None,
        "days_left": days_left,
        "race_name": primary.get("race_name", ""),
        "paces": paces,
        "predictions": preds,
    }


# ── 주간 데이터 ───────────────────────────────────────────────────────────────

def get_current_week_range() -> tuple[str, str]:
    """이번 주 월~일 날짜 반환"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def get_week_activities(week_start: str, user_id: int = 1) -> list[dict]:
    """특정 주(월~일) 활동 목록"""
    week_end = (datetime.fromisoformat(week_start) + timedelta(days=7)).strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, distance_km, avg_pace_sec, avg_heartrate,
               avg_cadence, elevation_gain, moving_time,
               training_type, ai_analysis_json, name
        FROM activities
        WHERE user_id = ? AND date >= ? AND date < ?
        ORDER BY date
    """, (user_id, week_start, week_end))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_current_week_plan(user_id: int = 1) -> dict | None:
    """이번 주 주간 계획"""
    week_start, _ = get_current_week_range()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT plan_json, total_planned_km, phase, acwr, week_start
        FROM weekly_plans WHERE user_id = ? AND week_start = ?
    """, (user_id, week_start))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    plan = json.loads(row["plan_json"]) if row["plan_json"] else {}
    plan["total_planned_km"] = row["total_planned_km"]
    plan["phase"] = row["phase"]
    plan["acwr"] = row["acwr"]
    plan["week_start"] = row["week_start"]
    return plan


def get_week_compliance(week_start: str, user_id: int = 1) -> float:
    """이번 주 이행도 (0~100)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT plan_json, total_planned_km FROM weekly_plans WHERE user_id = ? AND week_start = ?",
                   (user_id, week_start))
    row = cursor.fetchone()
    conn.close()
    if not row or not row["total_planned_km"]:
        return 0.0

    week_acts = get_week_activities(week_start, user_id)
    actual_km = sum(a["distance_km"] for a in week_acts)
    return round(min(actual_km / row["total_planned_km"] * 100, 100), 1)


# ── 월간 데이터 ───────────────────────────────────────────────────────────────

def get_available_months(user_id: int = 1) -> list[str]:
    """월 목록 반환 (최신순). 현재 달은 데이터 없어도 항상 포함."""
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT year_month FROM monthly_reports
        WHERE user_id = ? ORDER BY year_month DESC
    """, (user_id,))
    report_months = [r["year_month"] for r in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT strftime('%Y-%m', date) as ym
        FROM activities WHERE user_id = ?
        ORDER BY ym DESC LIMIT 12
    """, (user_id,))
    act_months = [r["ym"] for r in cursor.fetchall()]
    conn.close()

    all_months = list(dict.fromkeys([current_month] + report_months + act_months))
    return all_months


def get_monthly_report(year_month: str, user_id: int = 1) -> dict | None:
    """월간 리포트 조회"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM monthly_reports WHERE user_id = ? AND year_month = ?
    """, (user_id, year_month))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_monthly_weekly_km(year_month: str, user_id: int = 1) -> tuple[list, list]:
    """해당 월의 주차별 마일리지"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%W', date) as week_num,
               MIN(date) as week_start,
               ROUND(SUM(distance_km), 1) as km
        FROM activities
        WHERE user_id = ? AND strftime('%Y-%m', date) = ?
        GROUP BY week_num ORDER BY week_num
    """, (user_id, year_month))
    rows = cursor.fetchall()
    conn.close()

    labels = [f"{i+1}주차" for i in range(len(rows))]
    values = [r["km"] for r in rows]
    return labels, values


def get_monthly_activities_detail(year_month: str, user_id: int = 1) -> list[dict]:
    """해당 월 전체 활동 (날짜순)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, distance_km, avg_pace_sec, avg_heartrate, training_type
        FROM activities
        WHERE user_id = ? AND strftime('%Y-%m', date) = ?
        ORDER BY date
    """, (user_id, year_month))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ── 트렌드 & 점수 히스토리 ────────────────────────────────────────────────────

def get_score_history(user_id: int = 1, weeks: int = 12) -> list[dict]:
    """score_history 최근 N주"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT week_start, vdot, fitness_score, efficiency_score, compliance_score
        FROM score_history WHERE user_id = ?
        ORDER BY week_start DESC LIMIT ?
    """, (user_id, weeks))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return list(reversed(rows))  # 오래된 것 먼저


def get_weekly_km_history(user_id: int = 1, weeks: int = 10) -> tuple[list, list]:
    """최근 N주 주간 마일리지"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%G-W%V', date) as iso_week,
               ROUND(SUM(distance_km), 1) as km
        FROM activities
        WHERE user_id = ? AND date >= date('now', ?)
        GROUP BY iso_week ORDER BY iso_week
    """, (user_id, f"-{weeks * 7} days"))
    rows = cursor.fetchall()
    conn.close()

    def _week_label(iso_week: str) -> str:
        year, week = iso_week.split("-W")
        dt = datetime.strptime(f"{year}-W{week}-1", "%G-W%V-%u")
        return dt.strftime("%-m/%-d")

    labels = [_week_label(r["iso_week"]) for r in rows]
    values = [r["km"] for r in rows]
    return labels, values


def get_recent_activities_trend(user_id: int = 1, n: int = 15) -> list[dict]:
    """최근 N개 활동 트렌드용 데이터"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, distance_km, avg_pace_sec, avg_heartrate
        FROM activities
        WHERE user_id = ? AND avg_pace_sec > 0
        ORDER BY date DESC LIMIT ?
    """, (user_id, n))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return list(reversed(rows))


def save_score_snapshot(user_id: int = 1, reference_date: str | None = None) -> dict:
    """
    score_history 스냅샷 계산 & 저장.
    reference_date: 기준 날짜 (YYYY-MM-DD). None이면 오늘 기준 이번 주 월요일.
    백필 시에는 과거 날짜를 넘겨서 해당 시점 기준으로 계산.
    """
    from app.utils.vdot import calc_vdot_from_goal

    if reference_date:
        from datetime import date
        ref = date.fromisoformat(reference_date)
        # reference_date가 속한 주 월요일
        days_since_monday = ref.weekday()
        monday = ref - __import__('datetime').timedelta(days=days_since_monday)
        week_start = monday.isoformat()
    else:
        week_start, _ = get_current_week_range()
        reference_date = week_start

    vdot_info = get_vdot_info(user_id)
    vdot = vdot_info.get("vdot_pb")

    conn = get_connection()
    cursor = conn.cursor()

    # 체력 지수: reference_date 기준 이전 42일 주간 평균 km
    cursor.execute("""
        SELECT COALESCE(SUM(distance_km), 0) as total
        FROM activities
        WHERE user_id = ? AND date < ? AND date >= date(?, '-42 days')
    """, (user_id, reference_date, reference_date))
    total_42 = cursor.fetchone()["total"]
    weekly_avg = total_42 / 6
    fitness = min(100, int(weekly_avg * 2.5))

    # 효율 지수: 같은 기간 6:40~8:20/km 구간 평균 심박
    cursor.execute("""
        SELECT AVG(avg_heartrate) as avg_hr
        FROM activities
        WHERE user_id = ? AND avg_pace_sec BETWEEN 400 AND 500
        AND date < ? AND date >= date(?, '-42 days')
        AND avg_heartrate > 0
    """, (user_id, reference_date, reference_date))
    hr_row = cursor.fetchone()
    avg_hr = hr_row["avg_hr"] if hr_row["avg_hr"] else 160
    efficiency = max(0, min(100, int(210 - avg_hr)))

    # 이행 지수: 해당 주 실제 km / 계획 km (과거 주는 0)
    compliance = int(get_week_compliance(week_start, user_id))

    cursor.execute("""
        INSERT OR REPLACE INTO score_history
        (user_id, week_start, vdot, fitness_score, efficiency_score, compliance_score)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, week_start, vdot, fitness, efficiency, compliance))
    conn.commit()
    conn.close()

    return {
        "week_start": week_start,
        "vdot": vdot,
        "fitness": fitness,
        "efficiency": efficiency,
        "compliance": compliance,
    }


def backfill_score_history(user_id: int = 1) -> int:
    """
    activities 데이터가 있는 첫 주부터 오늘까지 모든 월요일에 대해
    score_history 스냅샷을 계산해서 채워넣음.
    이미 있는 row는 덮어씀 (INSERT OR REPLACE).
    반환: 처리한 주 수
    """
    import datetime

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MIN(date) FROM activities WHERE user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or not row[0]:
        return 0

    first_date = datetime.date.fromisoformat(row[0][:10])
    # 첫 활동이 속한 주 월요일
    first_monday = first_date - datetime.timedelta(days=first_date.weekday())
    today = datetime.date.today()

    count = 0
    current = first_monday
    while current <= today:
        save_score_snapshot(user_id=user_id, reference_date=current.isoformat())
        current += datetime.timedelta(weeks=1)
        count += 1

    return count


# ── ACWR ─────────────────────────────────────────────────────────────────────

def get_acwr(user_id: int = 1) -> dict:
    return calculate_acwr(user_id)


def get_zones(user_id: int = 1) -> dict:
    return get_training_zones(user_id)
