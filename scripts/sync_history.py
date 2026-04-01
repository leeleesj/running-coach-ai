"""
Strava 과거 활동 히스토리 동기화 스크립트
최초 1회 실행용

사용법:
    cd ~/Documents/workspace/running-coach-ai
    uv run python scripts/sync_history.py
"""

import asyncio
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import init_db, save_activity, save_splits, is_already_processed
from app.services.strava import get_all_activities, get_activity, parse_activity
from dotenv import load_dotenv

load_dotenv()

# 본인 athlete_id
ATHLETE_ID = 196195036


async def sync_history():
    """전체 Strava 활동 히스토리를 DB에 동기화"""

    print("=" * 50)
    print("Strava 히스토리 동기화 시작")
    print("=" * 50)

    # DB 초기화
    init_db()

    # 전체 활동 목록 가져오기
    print("\n📋 전체 활동 목록 가져오는 중...")
    activities = await get_all_activities(ATHLETE_ID)

    if not activities:
        print("❌ 활동을 가져오지 못했어요.")
        return

    print(f"총 {len(activities)}개 활동 발견\n")

    saved = 0
    skipped_duplicate = 0
    skipped_not_run = 0
    failed = 0

    for i, raw_summary in enumerate(activities, 1):
        activity_id = raw_summary.get("id")
        sport_type = raw_summary.get("sport_type", "")
        name = raw_summary.get("name", "")
        date = raw_summary.get("start_date_local", "")[:10]

        # 러닝만 저장
        if sport_type != "Run":
            print(f"[{i}/{len(activities)}] 스킵 (러닝 아님: {sport_type}) - {name}")
            skipped_not_run += 1
            continue

        # 이미 저장된 활동 스킵
        if is_already_processed(activity_id):
            print(f"[{i}/{len(activities)}] 스킵 (이미 저장됨) - {date} {name}")
            skipped_duplicate += 1
            continue

        # 상세 데이터 가져오기
        try:
            raw = await get_activity(activity_id, ATHLETE_ID)
            if not raw:
                print(f"[{i}/{len(activities)}] ❌ 실패 (데이터 없음) - {date} {name}")
                failed += 1
                continue

            activity = parse_activity(raw)
            activity_db_id = save_activity(activity)
            save_splits(activity_db_id, activity.splits)

            print(f"[{i}/{len(activities)}] ✅ 저장 - {activity.date} {activity.distance_km}km {activity.pace}")
            saved += 1

            # API 제한 방지: 10개마다 1초 대기
            if i % 10 == 0:
                print(f"\n⏳ API 제한 방지 대기 중... (1초)\n")
                await asyncio.sleep(1)

        except Exception as e:
            print(f"[{i}/{len(activities)}] ❌ 실패 - {date} {name}: {e}")
            failed += 1
            continue

    print("\n" + "=" * 50)
    print("동기화 완료!")
    print("=" * 50)
    print(f"✅ 저장:          {saved}개")
    print(f"⏭️  중복 스킵:     {skipped_duplicate}개")
    print(f"🚴 러닝 아님 스킵: {skipped_not_run}개")
    print(f"❌ 실패:          {failed}개")
    print(f"📊 전체:          {len(activities)}개")


if __name__ == "__main__":
    asyncio.run(sync_history())