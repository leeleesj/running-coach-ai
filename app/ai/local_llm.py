import httpx
import json
import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.models.database import get_training_zones, get_zone_for_heartrate

if TYPE_CHECKING:
    from app.models.activity import ActivityData

# Ollama 설정
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:14b"


def parse_llm_response(text: str) -> dict | None:
    """
    LLM JSON 응답 파싱
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


async def call_ollama(prompt: str, max_tokens: int = 1000) -> str:
    """
    Ollama API 호출
    POST http://localhost:11434/api/generate
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7,
                    "top_p": 0.9,
                }
            }
        )

    if response.status_code != 200:
        print(f"Ollama API 에러: {response.status_code} {response.text}")
        return ""

    result = response.json()
    return result.get("response", "")


def build_zones_prompt(zones: dict, avg_hr: float = None, max_hr: float = None) -> str:
    """
    훈련존 정보를 프롬프트 텍스트로 변환
    존별 심박 범위와 대응하는 페이스 범위 포함
    """
    z1 = zones["zone1_max"]
    z2 = zones["zone2_max"]
    z3 = zones["zone3_max"]
    z4 = zones["zone4_max"]

    zones_text = f"""
## 내 개인 심박존 (애플워치 기준, 반드시 준수)
존1 (매우 가벼움):  {z1}bpm 이하         → 페이스 10:00/km 이상
존2 (유산소 기반):  {z1+1}~{z2}bpm       → 페이스 약 8:30~9:30/km
존3 (유산소 파워):  {z2+1}~{z3}bpm       → 페이스 약 7:00~8:00/km
존4 (무산소 역치):  {z3+1}~{z4}bpm       → 페이스 약 5:30~6:30/km
존5 (최대 강도):    {z4+1}bpm 이상        → 페이스 5:30/km 미만

⚠️ 중요: 존2 훈련 목표 심박은 반드시 {z1+1}~{z2}bpm 범위여야 함"""

    # 오늘 운동의 존 정보 추가
    if avg_hr:
        avg_zone = get_zone_for_heartrate(avg_hr, zones)
        zones_text += f"\n\n## 오늘 운동 존 분석\n평균 심박 {avg_hr}bpm → {avg_zone}"

    if max_hr:
        max_zone = get_zone_for_heartrate(max_hr, zones)
        zones_text += f"\n최고 심박 {max_hr}bpm → {max_zone}"

    return zones_text


def build_terminology_prompt() -> str:
    """러닝 용어 사전 프롬프트"""
    return """
## 러닝 용어 (반드시 아래 용어만 사용, 임의 번역 금지)
- 존2 조깅 (Zone 2 Easy Run): 존2 심박 유지하며 천천히 달리기
- 템포런 (Tempo Run): 존3~4 경계, 불편하지만 유지 가능한 강도
- 인터벌 (Interval): 고강도 달리기와 회복 반복
- LSD (Long Slow Distance): 장거리 천천히 달리기, 존2 유지
- 회복 조깅 (Recovery Run): 존1~2, 매우 가볍게
- 휴식 (Rest): 완전 휴식"""


async def analyze_activity(
    activity: "ActivityData",
    weekly_activities: list,
    weather: dict = None,
    hr_correction: dict = None,
) -> str:
    """
    운동 데이터를 로컬 LLM(Qwen)으로 분석
    개인 훈련존 + 용어 사전 주입
    """

    # 이번 주 누적 데이터
    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    # 개인 훈련존 가져오기
    zones = get_training_zones()

    # 존 프롬프트 생성
    zones_text = build_zones_prompt(
        zones,
        avg_hr=activity.avg_heartrate,
        max_hr=activity.max_heartrate
    )

    # 용어 사전
    terminology_text = build_terminology_prompt()

    # km별 구간 데이터
    splits_text = ""
    for s in activity.splits:
        split_zone = get_zone_for_heartrate(s.avg_heartrate, zones)
        splits_text += f"  {s.km}km: 페이스 {s.pace}, 심박 {s.avg_heartrate}bpm ({split_zone})\n"

    # 날씨 텍스트
    weather_text = ""
    if weather:
        weather_text = f"""
## 운동 당시 날씨
- 기온: {weather['temperature']}°C
- 습도: {weather['humidity']}%
- 풍속: {weather['wind_speed']}m/s
- 날씨: {weather['sky']} ({weather['precipitation']})
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
{zones_text}
{terminology_text}

## 오늘 운동 데이터
- 날짜: {activity.date_display or activity.date}
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

## km별 구간 데이터 (존 분석 포함)
{splits_text}
{weather_text}
{hr_correction_text}
## 이번 주 누적
- 총 운동 횟수: {weekly_count}회
- 총 거리: {round(weekly_distance, 2)}km

## 목표
- 4월 26일 하프마라톤 완주 (21.1km)
- 심박수 안정화 (존2 훈련 비율 높이기)

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 절대 포함하지 마세요:

{{
  "summary": "오늘 운동 총평 (2~3문장, 존 정보 포함)",
  "heartrate_analysis": "심박수 존 분석 (개인 존 기준으로 정확하게, 2~3문장)",
  "pace_analysis": "구간별 페이스 패턴 분석 (2~3문장)",
  "tomorrow": {{
    "type": "훈련 종류 (휴식/존2 조깅/템포런/인터벌/LSD 중 하나)",
    "distance": "거리 (예: 5km)",
    "pace": "목표 페이스 (존 기준에 맞게)",
    "heartrate": "목표 심박수 (개인 존 범위 내로)"
  }},
  "marathon_status": "하프마라톤 준비 현황 한 줄 요약"
}}"""

    print(f"Ollama 분석 시작... (모델: {OLLAMA_MODEL})")
    text = await call_ollama(prompt, max_tokens=1000)
    print(f"Ollama 분석 완료!")
    return text


async def generate_weekly_schedule(
    activity: "ActivityData",
    weekly_activities: list,
    weather: dict = None,
    hr_correction: dict = None,
) -> str:
    """
    차주 훈련 스케줄 생성
    개인 훈련존 + 용어 사전 주입
    """

    goal_date = datetime(2026, 4, 26)
    today = datetime.now()
    days_left = (goal_date - today).days

    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    # 개인 훈련존
    zones = get_training_zones()
    zones_text = build_zones_prompt(zones)
    terminology_text = build_terminology_prompt()

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
{zones_text}
{terminology_text}

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
- 존2 훈련 비율 60% 이상 유지

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
각 날짜별로 한 줄: 날짜 | 훈련종류 | 거리 | 목표페이스 | 목표심박
마크다운 기호(##, **, * 등)는 사용하지 말고 일반 텍스트로만 작성해주세요.

⚠️ 중요 규칙:
- 존2 조깅 목표 심박은 반드시 {zones['zone1_max']+1}~{zones['zone2_max']}bpm 범위
- 존2 조깅 페이스는 약 8:30~9:30/km
- LSD도 존2 심박 유지 ({zones['zone1_max']+1}~{zones['zone2_max']}bpm)
- 주당 1~2회 휴식 포함
- 주말에 LSD 배치
- 총 주간 거리 이번 주 대비 10% 이내 증가"""

    print(f"Ollama 스케줄 생성 시작...")
    text = await call_ollama(prompt, max_tokens=800)
    print(f"Ollama 스케줄 생성 완료!")
    return text