"""
월간 코치 (P1-07)

매월 1일 실행:
  1. 지난 달 운동 집계 (거리/세션수/이행도/존 분포)
  2. Qwen으로 피트니스 평가 + 목표 진행률 분석
  3. DB 저장 + Notion 기록
  4. 텔레그램 발송 (요약 + Notion 목표 확인 요청)
"""

import json
import httpx
import re
from datetime import datetime, timedelta

from app.models.database import (
    get_active_goals, get_training_zones, get_zone_for_heartrate,
    get_monthly_activities, save_monthly_report,
)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:14b-ctx8k"


def _calc_zone_distribution(activities: list, zones: dict) -> dict:
    """운동 목록에서 존별 분포 계산 (심박 기준)"""
    counts = {"존1": 0, "존2": 0, "존3": 0, "존4": 0, "존5": 0}
    total = 0
    for a in activities:
        hr = a.get("avg_heartrate", 0)
        if hr and hr > 0:
            zone = get_zone_for_heartrate(hr, zones)
            zone_name = zone.split(" ")[0]
            counts[zone_name] = counts.get(zone_name, 0) + 1
            total += 1
    if total == 0:
        return counts
    return {k: round(v / total * 100, 1) for k, v in counts.items()}


def _calc_adherence(year_month: str, user_id: int = 1) -> float:
    """지난 달 이행도 계산: 실제 운동일 / 계획 운동일 * 100"""
    from app.models.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()

    # 지난 달의 주간 계획들 조회
    cursor.execute("""
        SELECT plan_json FROM weekly_plans
        WHERE user_id = ? AND week_start LIKE ?
    """, (user_id, f"{year_month}%"))
    plans = cursor.fetchall()
    conn.close()

    if not plans:
        return 0.0

    planned_sessions = 0
    for (plan_json,) in plans:
        try:
            plan = json.loads(plan_json)
            for s in plan.get("sessions", {}).values():
                if s.get("type", "휴식") != "휴식" and s.get("distance_km", 0) > 0:
                    planned_sessions += 1
        except Exception:
            continue

    actual_sessions = len([a for a in get_monthly_activities(year_month, user_id)])

    if planned_sessions == 0:
        return 0.0
    return round(min(actual_sessions / planned_sessions * 100, 100), 1)


async def generate_monthly_report(user_id: int = 1, year_month: str = None) -> dict | None:
    """
    월간 리포트 생성
    year_month: 'YYYY-MM' (None이면 지난 달)
    """
    if year_month is None:
        last_month = datetime.now().replace(day=1) - timedelta(days=1)
        year_month = last_month.strftime("%Y-%m")

    activities = get_monthly_activities(year_month, user_id)
    if not activities:
        print(f"{year_month} 운동 기록 없음")
        return None

    zones = get_training_zones(user_id)
    goals = get_active_goals(user_id)

    # 집계
    total_km = round(sum(a["distance_km"] for a in activities), 1)
    total_sessions = len(activities)
    avg_pace_sec = sum(a["avg_pace_sec"] for a in activities if a.get("avg_pace_sec")) / max(total_sessions, 1)
    avg_hr = sum(a["avg_heartrate"] for a in activities if a.get("avg_heartrate")) / max(total_sessions, 1)
    zone_dist = _calc_zone_distribution(activities, zones)
    adherence = _calc_adherence(year_month, user_id)

    # 목표 대비 진행률
    primary_goal = next((g for g in goals if g["priority"] == "primary"), None)
    goal_text = "목표 미설정"
    if primary_goal:
        sec = primary_goal.get("target_time_sec", 0)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
        goal_text = f"{primary_goal['event_type']} {time_str}"
        if primary_goal.get("target_date"):
            target = datetime.fromisoformat(primary_goal["target_date"])
            days_left = (target - datetime.now()).days
            goal_text += f" (D-{days_left})"

    # VDOT 계산
    from app.utils.vdot import calc_vdot_from_goal, format_vdot_summary, predict_all_races
    vdot_value = None
    vdot_text = ""
    if primary_goal:
        pb_sec = primary_goal.get("pb_time_sec") or primary_goal.get("target_time_sec", 0)
        vdot_value = calc_vdot_from_goal(primary_goal.get("event_type", ""), pb_sec)
        if vdot_value:
            vdot_text = "\n" + format_vdot_summary(
                event_type=primary_goal["event_type"],
                target_time_sec=primary_goal["target_time_sec"],
                pb_time_sec=primary_goal.get("pb_time_sec"),
            ) + "\n"

    # Qwen 분석 프롬프트
    pace_str = f"{int(avg_pace_sec // 60)}:{int(avg_pace_sec % 60):02d}/km" if avg_pace_sec > 0 else "N/A"
    activities_summary = "\n".join(
        f"  {a['date'][:10]}: {a['distance_km']}km, {int(a.get('avg_heartrate', 0))}bpm, {int(a.get('avg_pace_sec', 0)//60)}:{int(a.get('avg_pace_sec', 0)%60):02d}/km"
        for a in activities[-10:]  # 최근 10개만
    )

    prompt = f"""당신은 전문 러닝 코치입니다. {year_month} 훈련을 분석하고 JSON으로 응답하세요.

## {year_month} 훈련 요약
- 총 운동: {total_sessions}회, {total_km}km
- 평균 페이스: {pace_str}
- 평균 심박: {round(avg_hr, 1)}bpm
- 이행도: {adherence}%
- 존 분포: {zone_dist}

## 최근 운동 목록 (최대 10개)
{activities_summary}

## 목표
{goal_text}
{vdot_text}
## 개인 심박존
존2: {zones['zone1_max']+1}~{zones['zone2_max']}bpm
존3: {zones['zone2_max']+1}~{zones['zone3_max']}bpm
존4: {zones['zone3_max']+1}~{zones['zone4_max']}bpm

## 응답 형식
{{
  "fitness_assessment": "이달 피트니스 평가 (3~4문장: 강도 분포, 성장 여부, 약점)",
  "goal_progress": "목표 대비 진행 상황 (2문장)",
  "next_month_focus": "다음 달 핵심 포인트 (1~2문장)"
}}"""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"num_predict": 500, "temperature": 0.6}},
        )

    if resp.status_code != 200:
        print(f"월간 리포트 Ollama 에러: {resp.status_code}")
        return None

    raw = resp.json().get("response", "")
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    try:
        analysis = json.loads(raw.strip())
    except Exception:
        analysis = {"fitness_assessment": raw[:300], "goal_progress": "", "next_month_focus": ""}

    # DB 저장
    save_monthly_report(
        user_id=user_id,
        year_month=year_month,
        total_km=total_km,
        total_sessions=total_sessions,
        adherence_rate=adherence,
        zone_distribution=json.dumps(zone_dist, ensure_ascii=False),
        fitness_assessment=analysis.get("fitness_assessment", ""),
        goal_progress=analysis.get("goal_progress", ""),
    )

    return {
        "year_month": year_month,
        "total_km": total_km,
        "total_sessions": total_sessions,
        "adherence_rate": adherence,
        "zone_distribution": zone_dist,
        "goal_text": goal_text,
        "vdot": vdot_value,
        **analysis,
    }


def format_monthly_report_message(report: dict) -> str:
    """월간 리포트 텔레그램 메시지 포맷"""
    if not report:
        return "월간 리포트 생성 실패"

    ym = report.get("year_month", "")
    year, month = ym.split("-") if "-" in ym else ("", "")
    zone_dist = report.get("zone_distribution", {})
    zone_str = " | ".join(f"{k} {v}%" for k, v in zone_dist.items() if v > 0)

    vdot = report.get("vdot")
    vdot_str = f" | VDOT {vdot}" if vdot else ""

    return "\n".join([
        f"📊 {year}년 {month}월 훈련 리포트",
        "",
        f"🏃 총 {report['total_sessions']}회 | {report['total_km']}km | 이행도 {report['adherence_rate']}%{vdot_str}",
        f"💓 존 분포: {zone_str}",
        "",
        f"📝 {report.get('fitness_assessment', '')}",
        "",
        f"🎯 목표 ({report.get('goal_text', '')}) 진행: {report.get('goal_progress', '')}",
        "",
        f"➡️ 다음 달: {report.get('next_month_focus', '')}",
        "",
        "📌 Notion에서 목표를 확인/수정해주세요.",
    ])
