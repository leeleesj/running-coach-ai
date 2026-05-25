"""
Notion 쓰기 서비스 (P1-06)

시스템이 Notion에 자동으로 기록하는 세 가지:
  1. 훈련 일지: 운동 완료 시 (계획 vs 실적)
  2. 주간 계획: 매주 월요일
  3. 월간 리포트: 매월 1일
"""

import httpx

from app.core.logger import get_logger

logger = get_logger(__name__)
import json
from datetime import datetime

import app.config as config

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _rich_text(content: str) -> list:
    """Notion rich_text 프로퍼티 형식"""
    return [{"text": {"content": str(content)[:2000]}}]


async def post_training_log(
    activity: dict,
    planned_session: dict | None,
    ai_comment: str = "",
) -> str | None:
    """
    운동 완료 시 훈련 일지 DB에 기록
    반환: 생성된 Notion 페이지 ID (실패 시 None)
    """
    if not config.NOTION_TRAINING_LOG_DB_ID:
        return None

    date_str = activity.get("date", "")[:10]
    distance_km = activity.get("distance_km", 0)
    avg_hr = activity.get("avg_heartrate", 0)
    max_hr = activity.get("max_heartrate", 0)
    pace_sec = activity.get("avg_pace_sec", 0)
    pace_str = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}/km" if pace_sec else "N/A"
    cadence = activity.get("avg_cadence", 0)
    elevation = activity.get("elevation_gain", 0)
    calories = activity.get("calories", 0)
    strava_id = activity.get("strava_id")

    # 계획 대비
    if planned_session and planned_session.get("type", "휴식") != "휴식":
        plan_type = planned_session.get("type", "-")
        plan_km = planned_session.get("distance_km", 0)
        adherence = "✅ 완수" if distance_km >= plan_km * 0.8 else "⚠️ 미완수"
    else:
        plan_type = "계획 없음"
        plan_km = 0
        adherence = "-"

    title = f"{date_str} {activity.get('name', '러닝')}"

    props = {
        "이름":          {"title": _rich_text(title)},
        "날짜":          {"date": {"start": date_str}},
        "실제 종류":     {"rich_text": _rich_text(activity.get("training_type", "러닝"))},
        "실제 거리":     {"number": round(distance_km, 2)},
        "평균 심박":     {"number": round(avg_hr, 1) if avg_hr else 0},
        "최고 심박":     {"number": round(max_hr, 1) if max_hr else 0},
        "평균 페이스":   {"rich_text": _rich_text(pace_str)},
        "페이스(초/km)": {"number": round(pace_sec, 1) if pace_sec else 0},
        "고도 상승":     {"number": round(elevation, 1) if elevation else 0},
        "케이던스":      {"number": int(cadence) if cadence else 0},
        "칼로리":        {"number": int(calories) if calories else 0},
        "계획 종류":     {"rich_text": _rich_text(plan_type)},
        "계획 거리":     {"number": plan_km},
        "이행":          {"rich_text": _rich_text(adherence)},
        "AI 코멘트":     {"rich_text": _rich_text(ai_comment[:500])},
    }
    if strava_id:
        props["Strava ID"] = {"number": int(strava_id)}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NOTION_API}/pages",
            headers=_headers(),
            json={"parent": {"database_id": config.NOTION_TRAINING_LOG_DB_ID}, "properties": props},
        )

    if resp.status_code != 200:
        logger.error(f"Notion 훈련 일지 기록 실패: {resp.status_code} {resp.text[:200]}")
        return None

    page_id = resp.json().get("id")
    logger.info(f"Notion 훈련 일지 기록 완료: {title}")
    return page_id


async def post_weekly_plan(plan: dict) -> str | None:
    """
    주간 계획을 Notion 주간 계획 DB에 기록
    반환: 생성된 Notion 페이지 ID
    """
    if not config.NOTION_WEEKLY_PLAN_DB_ID:
        return None

    week_start = plan.get("week_start", "")
    phase = plan.get("phase", "base")
    phase_kr = {"base": "베이스", "build": "빌드", "peak": "피크", "taper": "테이퍼"}.get(phase, phase)
    total_km = plan.get("total_planned_km", 0)
    comment = plan.get("weekly_comment", "")

    # 세션 요약 텍스트
    day_kr = ["월", "화", "수", "목", "금", "토", "일"]
    day_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    sessions = plan.get("sessions", {})
    dates = plan.get("dates", {})

    schedule_lines = []
    for kr, key in zip(day_kr, day_keys):
        s = sessions.get(key, {})
        date_str = dates.get(key, "")[:10]
        s_type = s.get("type", "휴식")
        if s_type == "휴식" or s.get("distance_km", 0) == 0:
            schedule_lines.append(f"{kr}({date_str}) 휴식")
        else:
            schedule_lines.append(
                f"{kr}({date_str}) {s_type} {s.get('distance_km')}km "
                f"| {s.get('pace', '-')} | {s.get('heartrate', '-')}bpm"
            )

    schedule_text = "\n".join(schedule_lines)

    props = {
        "이름": {"title": _rich_text(f"{week_start} 주간 계획 ({phase_kr})")},
        "주 시작": {"date": {"start": week_start}},
        "훈련 단계": {"rich_text": _rich_text(phase_kr)},
        "목표 거리": {"number": total_km},
        "스케줄": {"rich_text": _rich_text(schedule_text)},
        "코멘트": {"rich_text": _rich_text(comment)},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NOTION_API}/pages",
            headers=_headers(),
            json={"parent": {"database_id": config.NOTION_WEEKLY_PLAN_DB_ID}, "properties": props},
        )

    if resp.status_code != 200:
        logger.error(f"Notion 주간 계획 기록 실패: {resp.status_code} {resp.text[:200]}")
        return None

    page_id = resp.json().get("id")
    logger.info(f"Notion 주간 계획 기록 완료: {week_start}")
    return page_id


async def post_monthly_report(report: dict) -> str | None:
    """
    월간 리포트를 Notion 월간 리포트 DB에 기록
    """
    if not config.NOTION_MONTHLY_REPORT_DB_ID:
        return None

    ym = report.get("year_month", "")
    zone_dist = report.get("zone_distribution", {})
    zone_str = " | ".join(f"{k} {v}%" for k, v in zone_dist.items() if v > 0)

    props = {
        "이름": {"title": _rich_text(f"{ym} 월간 리포트")},
        "월": {"rich_text": _rich_text(ym)},
        "총 거리": {"number": report.get("total_km", 0)},
        "운동 횟수": {"number": report.get("total_sessions", 0)},
        "이행도": {"number": report.get("adherence_rate", 0)},
        "존 분포": {"rich_text": _rich_text(zone_str)},
        "피트니스 평가": {"rich_text": _rich_text(report.get("fitness_assessment", ""))},
        "목표 진행": {"rich_text": _rich_text(report.get("goal_progress", ""))},
        "다음 달 포인트": {"rich_text": _rich_text(report.get("next_month_focus", ""))},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{NOTION_API}/pages",
            headers=_headers(),
            json={"parent": {"database_id": config.NOTION_MONTHLY_REPORT_DB_ID}, "properties": props},
        )

    if resp.status_code != 200:
        logger.error(f"Notion 월간 리포트 기록 실패: {resp.status_code} {resp.text[:200]}")
        return None

    page_id = resp.json().get("id")
    logger.info(f"Notion 월간 리포트 기록 완료: {ym}")
    return page_id
