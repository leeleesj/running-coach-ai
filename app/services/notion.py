import httpx
from datetime import datetime, timedelta
import app.config as config


async def create_weekly_report(
    weekly_activities: list,
    analysis: str,
    schedule: str,
) -> bool:
    """
    주간 리포트를 Notion DB에 생성
    매주 일요일 크론잡으로 호출 예정
    """

    # 이번 주 날짜 범위 계산
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week_str = f"{monday.strftime('%Y년 %-m월 %-d일')} ~ {sunday.strftime('%-m월 %-d일')}"

    # 몇 주차인지 계산
    week_number = today.isocalendar()[1]
    month = today.month
    title = f"{today.year}년 {month}월 {week_number}주차 리포트"

    # 이번 주 누적 통계
    total_distance = round(sum(a.get("distance", 0) / 1000 for a in weekly_activities), 2)
    total_count = len(weekly_activities)

    # 평균 페이스 계산
    avg_speeds = [a.get("average_speed", 0) for a in weekly_activities if a.get("average_speed", 0) > 0]
    if avg_speeds:
        avg_speed = sum(avg_speeds) / len(avg_speeds)
        pace_sec = 1000 / avg_speed
        avg_pace = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d} /km"
    else:
        avg_pace = "N/A"

    # 평균 심박수
    heartrates = [a.get("average_heartrate", 0) for a in weekly_activities if a.get("average_heartrate")]
    avg_heartrate = round(sum(heartrates) / len(heartrates), 1) if heartrates else 0

    # Notion API 호출
    url = "https://api.notion.com/v1/pages"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {config.NOTION_API_KEY}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json={
                "parent": {"database_id": config.NOTION_DATABASE_ID},
                "properties": {
                    "이름": {
                        "title": [{"text": {"content": title}}]
                    },
                    "기간": {
                        "date": {
                            "start": monday.strftime("%Y-%m-%d"),
                            "end": sunday.strftime("%Y-%m-%d"),
                        }
                    },
                    "총 거리": {"number": total_distance},
                    "운동 횟수": {"number": total_count},
                    "평균 페이스": {"rich_text": [{"text": {"content": avg_pace}}]},
                    "평균 심박": {"number": avg_heartrate},
                    "AI 분석": {"rich_text": [{"text": {"content": analysis[:2000]}}]},
                    "다음주 스케줄": {"rich_text": [{"text": {"content": schedule[:2000]}}]},
                },
            }
        )

    if response.status_code != 200:
        print(f"Notion API 에러: {response.status_code} {response.text}")
        return False

    print(f"Notion 주간 리포트 생성 완료! {title}")
    return True


async def generate_weekly_analysis(weekly_activities: list) -> str:
    """
    이번 주 전체 훈련 패턴 분석 (Claude API 호출)
    """
    import httpx

    total_distance = round(sum(a.get("distance", 0) / 1000 for a in weekly_activities), 2)
    total_count = len(weekly_activities)

    # 운동 목록 텍스트
    activities_text = ""
    for a in weekly_activities:
        date = a.get("start_date_local", "")[:10]
        distance = round(a.get("distance", 0) / 1000, 2)
        heartrate = a.get("average_heartrate", "N/A")
        speed = a.get("average_speed", 0)
        pace_sec = 1000 / speed if speed > 0 else 0
        pace = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}" if pace_sec else "N/A"
        activities_text += f"  - {date}: {distance}km, 페이스 {pace}/km, 심박 {heartrate}bpm\n"

    from datetime import datetime
    goal_date = datetime(2026, 4, 26)
    days_left = (goal_date - datetime.now()).days

    prompt = f"""당신은 전문 러닝 코치입니다. 이번 주 훈련 데이터를 분석하고 한국어로 주간 리포트를 작성해주세요.

## 이번 주 운동 목록
{activities_text}

## 이번 주 누적
- 총 횟수: {total_count}회
- 총 거리: {total_distance}km

## 목표
- 하프마라톤 완주: 4월 26일 (D-{days_left})
- 심박수 안정화 (존2 훈련 비율 높이기)

## 요청
1. 이번 주 훈련 총평 (3~4문장)
2. 훈련 강도 분석 (존2 비율, 과부하 여부)
3. 개선이 필요한 점
4. 다음 주 핵심 목표

간결하게 작성해주세요."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": config.CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            }
        )

    if response.status_code != 200:
        return "분석 실패"

    result = response.json()
    return result["content"][0]["text"]