"""
기존 활동에 ai_analysis_json 백필
Qwen으로 분석 후 DB 업데이트

실행: python -m scripts.backfill_analysis
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app.models.activity import ActivityData, SplitData
from app.models.database import (
    get_connection, get_training_zones, get_active_goals,
    update_activity_analysis,
)
from app.ai.local_llm import analyze_activity, parse_llm_response
from app.core.logger import get_logger

logger = get_logger(__name__)


def _fmt_pace(pace_sec: float) -> str:
    if not pace_sec or pace_sec <= 0:
        return "-"
    m = int(pace_sec // 60)
    s = int(pace_sec % 60)
    return f"{m}:{s:02d}/km"


def _fmt_time(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


def _fmt_date_display(date_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(date_iso)
        return dt.strftime("%Y년 %m월 %d일 %H:%M")
    except Exception:
        return date_iso


def load_activity_from_db(row: dict, conn) -> ActivityData:
    """DB 행 → ActivityData 재구성"""
    splits_rows = conn.execute(
        "SELECT * FROM splits WHERE activity_id = ? ORDER BY km",
        (row["id"],)
    ).fetchall()

    splits = []
    for s in splits_rows:
        pace_sec = s["pace_sec"] or 0
        splits.append(SplitData(
            km=s["km"],
            pace=_fmt_pace(pace_sec),
            pace_sec=pace_sec,
            avg_grade_adjusted_pace_sec=s["avg_grade_adjusted_pace_sec"],
            avg_heartrate=s["heartrate"] or 0,
            moving_time=_fmt_time(int(pace_sec * s["distance_m"] / 1000)) if pace_sec and s["distance_m"] else "0:00",
            distance_m=s["distance_m"] or 0,
            elevation_diff=s["elevation_diff"],
            pace_zone=s["pace_zone"],
        ))

    avg_pace_sec = row["avg_pace_sec"] or 0
    # DB에 moving_time이 초(int)로 저장된 경우 문자열로 변환
    raw_moving_time = row["moving_time"]
    if isinstance(raw_moving_time, int) or (isinstance(raw_moving_time, str) and raw_moving_time.isdigit()):
        moving_time_sec = int(raw_moving_time)
        moving_time_str = _fmt_time(moving_time_sec)
    elif raw_moving_time:
        moving_time_str = raw_moving_time
        moving_time_sec = int(avg_pace_sec * (row["distance_km"] or 0)) if avg_pace_sec else 0
    else:
        moving_time_sec = int(avg_pace_sec * (row["distance_km"] or 0)) if avg_pace_sec else 0
        moving_time_str = _fmt_time(moving_time_sec)

    return ActivityData(
        id=row["id"],
        name=row["name"] or "러닝",
        type="Run",
        date=row["date"],
        date_display=_fmt_date_display(row["date"]),
        distance_km=row["distance_km"] or 0,
        moving_time=moving_time_str,
        moving_time_sec=moving_time_sec,
        pace=_fmt_pace(avg_pace_sec),
        max_pace=_fmt_pace(row["max_pace_sec"]) if row["max_pace_sec"] else "-",
        avg_pace_sec=avg_pace_sec,
        max_pace_sec=row["max_pace_sec"],
        avg_heartrate=row["avg_heartrate"],
        max_heartrate=row["max_heartrate"],
        avg_cadence=row["avg_cadence"],
        elevation_gain=row["elevation_gain"] or 0,
        calories=row["calories"] or 0,
        splits=splits,
    )


def get_weekly_activities_from_db(date_iso: str, exclude_id: int, conn) -> list:
    """해당 날짜 기준 이번 주 활동 목록 (DB에서 조회)"""
    try:
        dt = datetime.fromisoformat(date_iso)
        monday = dt - timedelta(days=dt.weekday())
        sunday = monday + timedelta(days=6)
        rows = conn.execute(
            """SELECT distance_km, avg_heartrate FROM activities
               WHERE date >= ? AND date <= ? AND id != ?""",
            (monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d") + "T23:59:59", exclude_id)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


async def backfill():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM activities WHERE ai_analysis_json IS NULL ORDER BY date ASC"
    ).fetchall()

    goals = get_active_goals(user_id=1)
    total = len(rows)
    logger.info(f"백필 대상: {total}개")

    success, fail = 0, 0

    for i, row in enumerate(rows, 1):
        row = dict(row)
        aid = row["id"]
        date_str = row["date"][:10]

        logger.info(f"[{i}/{total}] ID={aid} {date_str} {row['distance_km']}km ...")

        try:
            activity = load_activity_from_db(row, conn)
            weekly = get_weekly_activities_from_db(row["date"], aid, conn)

            text = await analyze_activity(
                activity=activity,
                weekly_activities=weekly,
                weather=None,
                hr_correction=None,
                activity_db_id=aid,
                planned_session=None,
                goals=goals,
            )

            result = parse_llm_response(text)
            if result:
                update_activity_analysis(aid, result)
                success += 1
                logger.info(f"  ✅ 완료")
            else:
                fail += 1
                logger.warning(f"  ⚠️  JSON 파싱 실패 (raw: {text[:80]}...)")

        except Exception as e:
            fail += 1
            logger.error(f"  ❌ 오류: {e}")

    conn.close()
    logger.info(f"\n=== 백필 완료: 성공 {success} / 실패 {fail} / 전체 {total} ===")


if __name__ == "__main__":
    asyncio.run(backfill())
