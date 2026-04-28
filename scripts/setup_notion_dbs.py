"""
Notion DB 자동 생성 스크립트

코치 시스템에 필요한 5개 DB를 지정된 페이지 아래에 생성하고
.env에 추가할 ID를 출력합니다.

실행: uv run python scripts/setup_notion_dbs.py
"""

import httpx
import os
import sys
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# 부모 페이지 ID (https://www.notion.so/Goals-f91c76e1b22a47b1bddb389b059caa4f)
PARENT_PAGE_ID = "f91c76e1b22a47b1bddb389b059caa4f"

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def create_database(title: str, properties: dict) -> str | None:
    """Notion DB 생성 → DB ID 반환"""
    body = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "title": [{"text": {"content": title}}],
        "properties": properties,
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(f"{NOTION_API}/databases", headers=HEADERS, json=body)

    if resp.status_code != 200:
        print(f"  ❌ 생성 실패: {resp.status_code} {resp.text[:200]}")
        return None

    db_id = resp.json().get("id", "").replace("-", "")
    return db_id


def main():
    if not NOTION_API_KEY:
        print("❌ NOTION_API_KEY가 .env에 없습니다.")
        sys.exit(1)

    print(f"Notion DB 생성 시작 (부모 페이지: {PARENT_PAGE_ID})\n")

    results = {}

    # ── 1. Goals DB ───────────────────────────────────────────
    print("1. Goals DB 생성 중...")
    db_id = create_database("🎯 Goals", {
        "이름":       {"title": {}},
        "이벤트":     {"select": {"options": [
                          {"name": "10km",  "color": "blue"},
                          {"name": "half",  "color": "green"},
                          {"name": "full",  "color": "red"},
                      ]}},
        "목표기록":   {"rich_text": {}},
        "우선순위":   {"select": {"options": [
                          {"name": "primary",   "color": "red"},
                          {"name": "secondary", "color": "yellow"},
                      ]}},
        "대회명":     {"rich_text": {}},
        "대회날짜":   {"date": {}},
        "대회확정":   {"checkbox": {}},
        "주당훈련일수": {"number": {}},
        "주당최대거리": {"number": {}},
        "부상메모":   {"rich_text": {}},
        "상태":       {"select": {"options": [
                          {"name": "active",    "color": "green"},
                          {"name": "achieved",  "color": "blue"},
                          {"name": "abandoned", "color": "gray"},
                      ]}},
    })
    if db_id:
        results["NOTION_GOALS_DB_ID"] = db_id
        print(f"  ✅ 완료: {db_id}")

    # ── 2. Profile DB ─────────────────────────────────────────
    print("2. Profile DB 생성 중...")
    db_id = create_database("👤 Profile", {
        "이름":   {"title": {}},
        "날짜":   {"date": {}},
        "체중":   {"number": {}},
        "키":     {"number": {}},
    })
    if db_id:
        results["NOTION_PROFILE_DB_ID"] = db_id
        print(f"  ✅ 완료: {db_id}")

    # ── 3. 훈련 일지 DB ───────────────────────────────────────
    print("3. 훈련 일지 DB 생성 중...")
    db_id = create_database("📔 훈련 일지", {
        "이름":       {"title": {}},
        "날짜":       {"date": {}},
        "실제 종류":  {"rich_text": {}},
        "실제 거리":  {"number": {}},
        "평균 심박":  {"number": {}},
        "평균 페이스": {"rich_text": {}},
        "계획 종류":  {"rich_text": {}},
        "계획 거리":  {"number": {}},
        "이행":       {"rich_text": {}},
        "AI 코멘트":  {"rich_text": {}},
    })
    if db_id:
        results["NOTION_TRAINING_LOG_DB_ID"] = db_id
        print(f"  ✅ 완료: {db_id}")

    # ── 4. 주간 계획 DB ───────────────────────────────────────
    print("4. 주간 계획 DB 생성 중...")
    db_id = create_database("📅 주간 계획", {
        "이름":     {"title": {}},
        "주 시작":  {"date": {}},
        "훈련 단계": {"rich_text": {}},
        "목표 거리": {"number": {}},
        "스케줄":   {"rich_text": {}},
        "코멘트":   {"rich_text": {}},
    })
    if db_id:
        results["NOTION_WEEKLY_PLAN_DB_ID"] = db_id
        print(f"  ✅ 완료: {db_id}")

    # ── 5. 월간 리포트 DB ─────────────────────────────────────
    print("5. 월간 리포트 DB 생성 중...")
    db_id = create_database("📊 월간 리포트", {
        "이름":         {"title": {}},
        "월":           {"rich_text": {}},
        "총 거리":      {"number": {}},
        "운동 횟수":    {"number": {}},
        "이행도":       {"number": {}},
        "존 분포":      {"rich_text": {}},
        "피트니스 평가": {"rich_text": {}},
        "목표 진행":    {"rich_text": {}},
        "다음 달 포인트": {"rich_text": {}},
    })
    if db_id:
        results["NOTION_MONTHLY_REPORT_DB_ID"] = db_id
        print(f"  ✅ 완료: {db_id}")

    # ── 결과 출력 ─────────────────────────────────────────────
    print("\n" + "="*50)
    print(".env에 아래 내용을 추가하세요:\n")
    for key, val in results.items():
        print(f"{key}={val}")
    print("="*50)

    if len(results) == 5:
        print("\n✅ 5개 DB 모두 생성 완료!")
    else:
        print(f"\n⚠️ {len(results)}/5개만 생성됨. 실패한 항목을 확인하세요.")


if __name__ == "__main__":
    main()
