import httpx
import json
import re
import app.config as config
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.activity import ActivityData


def parse_claude_response(text: str) -> dict | None:
    """
    Claude JSON 응답 파싱
    ```json ... ``` 블록 제거 후 파싱
    실패하면 None 반환
    """
    try:
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        return json.loads(text)
    except Exception as e:
        print(f"JSON 파싱 실패: {e}")
        return None


async def analyze_activity(
    activity: "ActivityData",
    weekly_activities: list,
    weather: dict = None,
    hr_correction: dict = None,
) -> str:
    """
    운동 데이터를 Claude API로 분석
    JSON 형식으로 응답 요청
    """

    # 이번 주 누적 데이터 계산
    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    # km별 구간 데이터 텍스트로 변환
    splits_text = ""
    for s in activity.splits:
        splits_text += f"  {s.km}km: 페이스 {s.pace}, 심박 {s.avg_heartrate}bpm\n"

    # 날씨 정보 텍스트 변환
    weather_text = ""
    if weather:
        weather_text = f"""
## 운동 당시 날씨
- 기온: {weather['temperature']}°C
- 습도: {weather['humidity']}%
- 풍속: {weather['wind_speed']}m/s
- 날씨: {weather['sky']} ({weather['precipitation']})
- 강수확률: {weather['rain_probability']}%
- 러닝 조건: {weather['running_condition']}
"""

    # 심박 보정 텍스트
    hr_correction_text = ""
    if hr_correction and hr_correction.get("correction"):
        hr_correction_text = f"""
## 날씨 기반 심박수 보정
- 보정값: {hr_correction['correction']:+.1f}bpm
- 보정 후 평균 심박: {hr_correction.get('adjusted_heartrate', 'N/A')}bpm
- 설명: {hr_correction['comment']}
"""

    prompt = f"""당신은 전문 러닝 코치입니다. 다음 운동 데이터를 분석해주세요.

## 오늘 운동 데이터
- 날짜: {activity.date}
- 운동명: {activity.name}
- 거리: {activity.distance_km}km
- 시간: {activity.moving_time}
- 평균 페이스: {activity.pace}
- 최고 페이스: {activity.max_pace}
- 평균 심박수: {activity.avg_heartrate}bpm
- 최고 심박수: {activity.max_heartrate}bpm
- 케이던스: {activity.avg_cadence}spm
- 칼로리: {activity.calories}kcal
- 고도 상승: {activity.elevation_gain}m

## km별 구간 데이터
{splits_text}
{weather_text}
{hr_correction_text}
## 이번 주 누적
- 총 운동 횟수: {weekly_count}회
- 총 거리: {round(weekly_distance, 2)}km

## 목표
- 4월 26일 하프마라톤 완주 (21.1km)
- 심박수 안정화 (존2 훈련 비율 높이기)
- 오래 빠르게 뛰기

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 절대 포함하지 마세요:

{{
  "summary": "오늘 운동 총평 (2~3문장, 핵심만 간결하게)",
  "heartrate_analysis": "심박수 존 분석 (2~3문장, 존2 유지 여부와 개선점)",
  "pace_analysis": "구간별 페이스 패턴 분석 (2~3문장, 초반/중반/후반 패턴)",
  "tomorrow": {{
    "type": "훈련 종류 (휴식/존2조깅/템포런/인터벌/LSD 중 하나)",
    "distance": "거리 (예: 5km)",
    "pace": "목표 페이스 (예: 8:30-9:00 /km)",
    "heartrate": "목표 심박수 (예: 140-150bpm)"
  }},
  "marathon_status": "하프마라톤 준비 현황 한 줄 요약"
}}"""

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
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            }
        )

    if response.status_code != 200:
        print(f"Claude API 에러: {response.status_code} {response.text}")
        return ""

    result = response.json()
    return result["content"][0]["text"]


async def generate_weekly_schedule(
    activity: "ActivityData",
    weekly_activities: list,
    weather: dict = None,
    hr_correction: dict = None,
) -> str:
    """
    차주 훈련 스케줄 생성
    오늘 운동 + 이번 주 누적 데이터 기반
    """

    goal_date = datetime(2026, 4, 26)
    today = datetime.now()
    days_left = (goal_date - today).days

    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    next_monday = today + timedelta(days=(7 - today.weekday()))
    dates = [(next_monday + timedelta(days=i)).strftime("%m/%d (%a)") for i in range(7)]
    days_kr = ["월", "화", "수", "목", "금", "토", "일"]
    schedule_dates = [f"{dates[i]} ({days_kr[i]})" for i in range(7)]

    if hasattr(activity, "distance_km"):
        distance_km = activity.distance_km
        pace = activity.pace
        avg_heartrate = activity.avg_heartrate
    else:
        distance_km = activity.get("distance_km", 0)
        pace = activity.get("pace", "N/A")
        avg_heartrate = activity.get("avg_heartrate", 0)

    adjusted_heartrate = hr_correction.get("adjusted_heartrate", "N/A") if hr_correction else "N/A"

    prompt = f"""당신은 전문 러닝 코치입니다. 다음 주 훈련 스케줄을 작성해주세요.

## 오늘 운동
- 거리: {distance_km}km
- 페이스: {pace}
- 평균 심박: {avg_heartrate}bpm
- 보정 심박: {adjusted_heartrate}bpm

## 이번 주 누적
- 총 횟수: {weekly_count}회
- 총 거리: {round(weekly_distance, 2)}km

## 목표
- 하프마라톤 완주: 4월 26일 (D-{days_left})
- 심박수 안정화 (존2 훈련 비율 높이기)

## 다음 주 날짜
{schedule_dates[0]}
{schedule_dates[1]}
{schedule_dates[2]}
{schedule_dates[3]}
{schedule_dates[4]}
{schedule_dates[5]}
{schedule_dates[6]}

## 요청
위 날짜에 맞게 다음 주 7일 훈련 스케줄을 작성해주세요.
각 날짜별로 한 줄로: 날짜 | 훈련종류 | 거리 | 목표페이스 | 목표심박
마크다운 기호(##, **, * 등)는 사용하지 말고 일반 텍스트로만 작성해주세요.

규칙:
- 하프마라톤 D-{days_left}일 기준 적절한 훈련량
- 주당 1-2회 휴식일 포함
- 주말에 LSD 배치
- 존2 훈련 비율 60% 이상
- 총 주간 거리는 이번 주 대비 10% 이내 증가"""

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
                "max_tokens": 800,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            }
        )

    if response.status_code != 200:
        print(f"Claude API 에러: {response.status_code} {response.text}")
        return "스케줄 생성에 실패했어요."

    result = response.json()
    return result["content"][0]["text"]