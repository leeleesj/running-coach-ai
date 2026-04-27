"""
Personal RAG 인덱스 초기 구축 스크립트
DB의 모든 운동 데이터를 ChromaDB에 임베딩 저장

실행: uv run python scripts/build_personal_rag.py
"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.personal_rag import get_personal_rag, activity_to_text
import sqlite3

DB_PATH = Path("data/running_coach.db")


def main():
    print("Personal RAG 인덱스 구축 시작\n")

    rag = get_personal_rag()

    # 기존 인덱스 상태 확인
    existing = rag.collection.count()
    print(f"기존 인덱스: {existing}개")

    # 전체 인덱싱
    count = rag.build_index()
    print(f"인덱싱 완료: {count}개\n")

    # 검색 품질 수동 확인 (최근 운동으로 테스트)
    print("=" * 50)
    print("검색 품질 확인 (최근 운동 → 유사 과거 운동 Top 3)")
    print("=" * 50)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM activities WHERE type='Run' AND avg_heartrate IS NOT NULL "
        "ORDER BY date DESC LIMIT 3"
    )
    recent = cursor.fetchall()
    conn.close()

    for activity in recent:
        act = dict(activity)
        print(f"\n쿼리: {act['date'][:10]} | {act['distance_km']:.1f}km | "
              f"심박 {act['avg_heartrate']:.0f}bpm")
        print(f"  텍스트: {activity_to_text(act)}")

        similar = rag.search_similar(act, n_results=3, exclude_db_id=act["id"])
        print("  유사 과거 운동:")
        for item in similar:
            meta = item["metadata"]
            print(f"    [{meta['date']}] {meta['distance_km']:.1f}km "
                  f"심박 {meta['avg_heartrate']:.0f}bpm "
                  f"유사도:{1 - item['distance']:.3f}")

        context = rag.get_rag_context(act, exclude_db_id=act["id"])
        if context:
            print("\n  RAG 컨텍스트 (프롬프트 주입 내용):")
            for line in context.split("\n"):
                print(f"    {line}")


if __name__ == "__main__":
    main()
