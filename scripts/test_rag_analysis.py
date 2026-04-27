"""
Personal RAG 주입 테스트 스크립트
DB에서 운동 3개를 꺼내 analyze_activity 직접 호출 → RAG 컨텍스트 주입 확인

실행: uv run python scripts/test_rag_analysis.py
"""

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.activity import ActivityData, SplitData
from app.models.database import DB_PATH
from app.rag.personal_rag import get_personal_rag


def load_activity_from_db(db_id: int) -> tuple[ActivityData, int]:
    """DB에서 ActivityData 복원"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM activities WHERE id = ?", (db_id,))
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"db_id={db_id} 없음")
    act = dict(row)

    cursor.execute(
        "SELECT * FROM splits WHERE activity_id = ? ORDER BY km", (db_id,)
    )
    split_rows = cursor.fetchall()
    conn.close()

    # pace 포맷 헬퍼
    def sec_to_pace(sec):
        if not sec:
            return "N/A"
        return f"{int(sec // 60)}:{int(sec % 60):02d} /km"

    def sec_to_pace_str(sec):
        if not sec:
            return "N/A"
        return f"{int(sec // 60)}:{int(sec % 60):02d} /km"

    splits = [
        SplitData(
            km=s["km"],
            pace=sec_to_pace_str(s["pace_sec"]),
            pace_sec=s["pace_sec"] or 0,
            avg_grade_adjusted_pace_sec=s["avg_grade_adjusted_pace_sec"] or 0,
            avg_heartrate=s["heartrate"] or 0,
            moving_time="0:00",
            distance_m=s["distance_m"] or 0,
            elevation_diff=s["elevation_diff"] or 0,
            pace_zone=s["pace_zone"] or 0,
        )
        for s in split_rows
    ]

    pace_sec = act.get("avg_pace_sec") or 0
    max_pace_sec = act.get("max_pace_sec") or 0
    moving_time_sec = act.get("moving_time") or 0
    moving_time_str = f"{moving_time_sec // 3600}:{(moving_time_sec % 3600) // 60:02d}:{moving_time_sec % 60:02d}"

    activity = ActivityData(
        id=act["strava_id"],
        name=act["name"] or "Run",
        type=act["type"] or "Run",
        workout_type=act["workout_type"],
        device_name=act["device_name"],
        date=act["date"],
        date_display=act.get("date_display") or act["date"][:10],
        distance_km=round(act["distance_km"] or 0, 2),
        moving_time=moving_time_str,
        moving_time_sec=moving_time_sec,
        elapsed_time_sec=act["elapsed_time"] or 0,
        avg_pace_sec=pace_sec,
        max_pace_sec=max_pace_sec,
        pace=sec_to_pace(pace_sec),
        max_pace=sec_to_pace(max_pace_sec),
        avg_heartrate=act["avg_heartrate"] or 0,
        max_heartrate=act["max_heartrate"] or 0,
        avg_heartrate_adjusted=act.get("avg_heartrate_adjusted"),
        hr_correction=act.get("hr_correction"),
        hr_correction_comment=act.get("hr_correction_comment"),
        avg_cadence=act["avg_cadence"] or 0,
        elevation_gain=act["elevation_gain"] or 0,
        elev_high=act.get("elev_high"),
        elev_low=act.get("elev_low"),
        calories=act["calories"] or 0,
        suffer_score=act.get("suffer_score"),
        perceived_exertion=act.get("perceived_exertion"),
        pr_count=act.get("pr_count") or 0,
        achievement_count=act.get("achievement_count") or 0,
        pr_rank=act.get("pr_rank_similar"),
        trend_direction=act.get("trend_direction"),
        splits=splits,
    )
    return activity, db_id


async def test_one(db_id: int, label: str):
    print(f"\n{'='*60}")
    print(f"테스트: {label} (db_id={db_id})")
    print("="*60)

    activity, activity_db_id = load_activity_from_db(db_id)
    print(f"운동: {activity.date[:10]} | {activity.distance_km}km | "
          f"심박 {activity.avg_heartrate}bpm | 페이스 {activity.pace}")

    # RAG 컨텍스트 단독 확인
    print("\n[RAG 컨텍스트]")
    rag = get_personal_rag()
    activity_dict = {
        "date": activity.date,
        "distance_km": activity.distance_km,
        "avg_pace_sec": activity.avg_pace_sec,
        "avg_heartrate": activity.avg_heartrate,
        "max_heartrate": activity.max_heartrate,
        "avg_cadence": activity.avg_cadence,
        "elevation_gain": activity.elevation_gain,
        "calories": activity.calories,
    }
    context = rag.get_rag_context(activity_dict, exclude_db_id=activity_db_id)
    if context:
        print(context)
    else:
        print("(RAG 컨텍스트 없음 — 인덱스 비어있거나 유사 운동 없음)")

    # analyze_activity 호출
    print("\n[Qwen 분석 시작...]")
    from app.ai.local_llm import analyze_activity
    result = await analyze_activity(
        activity=activity,
        weekly_activities=[],
        weather=None,
        hr_correction=None,
        activity_db_id=activity_db_id,
    )

    # 결과 파싱
    from app.ai.local_llm import parse_llm_response
    parsed = parse_llm_response(result)

    print("\n[Qwen 출력]")
    if parsed:
        print(f"총평:    {parsed.get('summary', '')}")
        print(f"심박분석: {parsed.get('heartrate_analysis', '')}")
        print(f"페이스:  {parsed.get('pace_analysis', '')}")
        tomorrow = parsed.get("tomorrow", {})
        print(f"내일훈련: {tomorrow.get('type','')} {tomorrow.get('distance','')} "
              f"페이스:{tomorrow.get('pace','')} 심박:{tomorrow.get('heartrate','')}")
        print(f"마라톤:  {parsed.get('marathon_status', '')}")
        print(f"과거비교: {parsed.get('progress', '(없음)')}")
    else:
        print(result[:500])


async def main():
    # 인덱스 확인
    rag = get_personal_rag()
    count = rag.collection.count()
    print(f"ChromaDB 인덱스: {count}개 운동")
    if count == 0:
        print("인덱스 없음. build_personal_rag.py 먼저 실행하세요.")
        return

    # 테스트할 운동 3개: 존2 / 존4 / 존3
    test_cases = [
        (116, "존2 정상 훈련"),   # avg_heartrate ~145bpm
        (107, "존4 고강도"),      # avg_heartrate ~168bpm
        (65,  "존3 중강도"),      # avg_heartrate ~158bpm
    ]

    for db_id, label in test_cases:
        try:
            await test_one(db_id, label)
        except Exception as e:
            print(f"[{label}] 실패: {e}")

    print(f"\n{'='*60}")
    print("테스트 완료")


if __name__ == "__main__":
    asyncio.run(main())
