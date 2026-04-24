"""
테스트셋 빌드 스크립트
DB에서 시나리오별 20개 케이스를 선정해 evaluation/test_cases.json 생성

실행: uv run python evaluation/build_test_cases.py
"""

import json
import sqlite3
from pathlib import Path

from evaluation.rubric import get_expected_zone

DB_PATH = Path("data/running_coach.db")
OUTPUT_PATH = Path("evaluation/test_cases.json")

# 시나리오별 선정된 DB ID (분석 완료)
# 존 분포: zone2×5, zone3×7, zone4×6, zone5×2 = 총 20개
SELECTED_IDS_BY_SCENARIO = {
    "zone2_normal":   [61, 116, 125, 126, 130],   # 존2 정상 훈련 (정확성 정답 케이스)
    "zone4_high":     [66, 107, 122, 123, 136],   # 존4 고강도 (베이스라인 오류 케이스)
    "zone5_max":      [1, 135],                   # 존5 최대 강도
    "zone3_moderate": [8, 32, 65, 124, 132],      # 존3 중강도
    "short_run":      [64, 134, 137],             # 짧은 거리 (<5km)
}


def sec_to_pace(pace_sec: float) -> str:
    """초/km → '분:초 /km' 형식 변환"""
    if not pace_sec:
        return "N/A"
    minutes = int(pace_sec // 60)
    seconds = int(pace_sec % 60)
    return f"{minutes}:{seconds:02d} /km"


def build_activity_text(activity: dict, splits: list) -> str:
    """
    평가 프롬프트에 들어갈 운동 데이터 텍스트 생성
    Claude 심사위원이 정확하게 판단할 수 있도록 수치 포함
    """
    splits_text = ""
    for s in splits:
        if s.get("heartrate") and s.get("pace_sec"):
            splits_text += (
                f"  {s['km']}km: 페이스 {sec_to_pace(s['pace_sec'])}, "
                f"심박 {s['heartrate']}bpm\n"
            )

    return f"""날짜: {activity['date'][:10]}
거리: {activity['distance_km']}km
평균 페이스: {sec_to_pace(activity['avg_pace_sec'])}
평균 심박수: {activity['avg_heartrate']}bpm
최고 심박수: {activity['max_heartrate']}bpm
고도 상승: {activity.get('elevation_gain', 0)}m
칼로리: {activity.get('calories', 0)}kcal

km별 구간:
{splits_text.rstrip()}"""


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 전체 선정 ID 목록
    all_ids = []
    id_to_scenario = {}
    for scenario, ids in SELECTED_IDS_BY_SCENARIO.items():
        for db_id in ids:
            all_ids.append(db_id)
            id_to_scenario[db_id] = scenario

    placeholders = ",".join("?" * len(all_ids))
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM activities WHERE id IN ({placeholders})",
        all_ids
    )
    rows = cursor.fetchall()

    test_cases = []
    for row in rows:
        activity = dict(row)
        db_id = activity["id"]

        # km별 구간 데이터 조회
        cursor.execute(
            "SELECT * FROM splits WHERE activity_id = ? ORDER BY km",
            (db_id,)
        )
        splits = [dict(s) for s in cursor.fetchall()]

        # splits_json fallback: splits 테이블이 비어있으면 activities.splits_json 사용
        if not splits and activity.get("splits_json"):
            try:
                raw_splits = json.loads(activity["splits_json"])
                splits = [
                    {
                        "km": s.get("km"),
                        "pace_sec": s.get("pace_sec"),
                        "heartrate": s.get("avg_heartrate"),
                        "distance_m": s.get("distance_m"),
                        "elevation_diff": s.get("elevation_diff"),
                    }
                    for s in raw_splits
                ]
            except Exception:
                splits = []

        scenario = id_to_scenario[db_id]
        expected_zone = get_expected_zone(activity["avg_heartrate"])

        test_case = {
            "id": f"test_{len(test_cases)+1:03d}",
            "db_id": db_id,
            "scenario": scenario,
            "expected_zone": expected_zone,
            "activity": {
                "date": activity["date"],
                "distance_km": round(activity["distance_km"], 2),
                "avg_pace_sec": activity["avg_pace_sec"],
                "max_pace_sec": activity["max_pace_sec"],
                "avg_heartrate": activity["avg_heartrate"],
                "max_heartrate": activity["max_heartrate"],
                "avg_cadence": activity["avg_cadence"],
                "elevation_gain": activity["elevation_gain"],
                "calories": activity["calories"],
                "splits": splits,
            },
            "activity_text": build_activity_text(activity, splits),
            # 평가 실행 시 채워질 필드
            "qwen_output": None,
            "judge_scores": [],    # Claude 채점 결과 3회
            "final_scores": None,  # 3회 평균
        }
        test_cases.append(test_case)

    conn.close()

    # 날짜순 정렬
    test_cases.sort(key=lambda x: x["activity"]["date"])

    OUTPUT_PATH.write_text(
        json.dumps(test_cases, ensure_ascii=False, indent=2)
    )

    print(f"테스트셋 생성 완료: {len(test_cases)}개 케이스")
    print()

    # 시나리오별 분포 출력
    from collections import Counter
    scenario_counts = Counter(tc["scenario"] for tc in test_cases)
    zone_counts = Counter(tc["expected_zone"] for tc in test_cases)

    print("시나리오별 분포:")
    for scenario, count in sorted(scenario_counts.items()):
        print(f"  {scenario}: {count}개")

    print("\n존별 분포:")
    for zone, count in sorted(zone_counts.items()):
        print(f"  {zone}: {count}개")

    print(f"\n저장 경로: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
