import httpx
import app.config as config


async def analyze_activity(activity: dict, weekly_activities: list, weather: dict = None) -> str:
    """
    운동 데이터를 Claude API로 분석
    
    activity: parse_activity()로 파싱된 오늘 운동 데이터
    weekly_activities: 이번 주 활동 목록 (누적 현황용)
    """

    # 이번 주 누적 데이터 계산
    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    # km별 구간 데이터 텍스트로 변환
    splits_text = ""
    for s in activity.get("splits", []):
        splits_text += f"  {s['km']}km: 페이스 {s['pace']}, 심박 {s['avg_heartrate']}bpm\n"
    
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

    # 프롬프트 작성
    prompt = f"""당신은 전문 러닝 코치입니다. 다음 운동 데이터를 분석하고 피드백을 한국어로 제공해주세요.

## 오늘 운동 데이터
- 날짜: {activity['date']}
- 운동명: {activity['name']}
- 거리: {activity['distance_km']}km
- 시간: {activity['moving_time']}
- 평균 페이스: {activity['pace']}
- 최고 페이스: {activity['max_pace']}
- 평균 심박수: {activity['avg_heartrate']}bpm
- 최고 심박수: {activity['max_heartrate']}bpm
- 케이던스: {activity['avg_cadence']}spm
- 칼로리: {activity['calories']}kcal
- 고도 상승: {activity['elevation_gain']}m

## km별 구간 데이터
{splits_text}
{weather_text}
## 이번 주 누적
- 총 운동 횟수: {weekly_count}회
- 총 거리: {round(weekly_distance, 2)}km

## 목표
- 4월 26일 하프마라톤 완주 (21.1km)
- 심박수 안정화 (존2 훈련 비율 높이기)
- 오래 빠르게 뛰기

## 분석 요청
다음 항목을 분석해주세요:
1. 오늘 운동 총평 (2~3문장)
2. 심박수 존 분석 (존2 유지 여부, 개선점)
3. 구간별 페이스 패턴 분석 (초반 돌진, 후반 처짐 등)
4. 내일 추천 훈련 (종류, 거리, 목표 페이스, 목표 심박)
5. 하프마라톤 준비 현황 (한 줄)

답변은 간결하게, 각 항목별로 구분해서 작성해주세요."""

    # Claude API 호출
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
        return "분석을 불러오지 못했어요."

    result = response.json()
    return result["content"][0]["text"]