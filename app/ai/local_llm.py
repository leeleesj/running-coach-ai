import httpx
import json
import re
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.logger import get_logger
from app.models.database import get_training_zones, get_zone_for_heartrate

if TYPE_CHECKING:
    from app.models.activity import ActivityData

# Ollama 설정
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:14b-ctx8k"


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
        logger.warning(f"JSON 파싱 실패: {e}")
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
        logger.error(f"Ollama API 에러: {response.status_code} {response.text}")
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
    activity_db_id: int = None,
    planned_session: dict = None,
    goals: list = None,
) -> str:
    """
    운동 데이터를 로컬 LLM(Qwen)으로 분석
    개인 훈련존 + 용어 사전 + Personal RAG + 계획 세션 컨텍스트 주입
    planned_session: 오늘 주간 계획에서 가져온 세션 (없으면 None)
    """

    # 이번 주 누적 데이터
    weekly_distance = sum(a.get("distance", 0) / 1000 for a in weekly_activities)
    weekly_count = len(weekly_activities)

    # Personal RAG: 유사 과거 운동 비교 컨텍스트
    rag_context = ""
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
    try:
        from app.rag.personal_rag import get_personal_rag
        rag = get_personal_rag()
        if rag.collection.count() > 0:
            rag_context = rag.get_rag_context(activity_dict, exclude_db_id=activity_db_id)
            if rag_context:
                logger.debug("Personal RAG 컨텍스트 주입 완료")
    except Exception as e:
        logger.warning(f"Personal RAG 조회 실패 (무시하고 계속): {e}")

    # Knowledge RAG: 러닝 전문 지식 컨텍스트
    knowledge_context = ""
    try:
        from app.rag.knowledge_rag import get_knowledge_rag
        krag = get_knowledge_rag()
        if krag.collection.count() > 0:
            knowledge_context = krag.get_knowledge_context(
                activity=activity_dict,
                avg_heartrate=activity.avg_heartrate,
            )
            if knowledge_context:
                logger.debug("Knowledge RAG 컨텍스트 주입 완료")
    except Exception as e:
        logger.warning(f"Knowledge RAG 조회 실패 (무시하고 계속): {e}")

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

    # RAG 섹션: 존/용어 다음, 운동 데이터 바로 앞에 배치
    rag_parts = []
    if rag_context:
        rag_parts.append(rag_context)
    if knowledge_context:
        rag_parts.append(knowledge_context)
    rag_section = "\n" + "\n\n".join(rag_parts) + "\n" if rag_parts else ""

    # 목표/부상 컨텍스트
    goal_section = ""
    if goals:
        primary = next((g for g in goals if g["priority"] == "primary"), None)
        if primary:
            sec = primary.get("target_time_sec", 0)
            h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
            time_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            days_left = ""
            if primary.get("target_date"):
                from datetime import datetime
                dt = datetime.fromisoformat(primary["target_date"])
                days_left = f" (D-{(dt - datetime.now()).days})"
            injury = f"\n- 부상 상태: {primary['injury_notes']}" if primary.get("injury_notes") else ""
            goal_section = f"""
## 훈련 목표 및 현재 상태
- 목표: {primary['event_type']} {time_str}{days_left}
- 주당 훈련 가능: {primary.get('weekly_days_available', 4)}일 / 최대 {primary.get('max_weekly_km', 30)}km{injury}
"""

    # 오늘 계획 세션 텍스트 (있을 때만)
    plan_section = ""
    if planned_session and planned_session.get("type", "휴식") != "휴식":
        plan_section = f"""
## 오늘 계획 세션
- 종류: {planned_session.get('type', '-')}
- 계획 거리: {planned_session.get('distance_km', 0)}km
- 계획 페이스: {planned_session.get('pace', '-')}
- 계획 심박: {planned_session.get('heartrate', '-')}bpm
"""

    prompt = f"""당신은 전문 러닝 코치입니다. 다음 운동 데이터를 분석해주세요.
{zones_text}
{terminology_text}
{goal_section}{rag_section}
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
{hr_correction_text}{plan_section}
## 이번 주 누적
- 총 운동 횟수: {weekly_count}회
- 총 거리: {round(weekly_distance, 2)}km

## 응답 형식
반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 절대 포함하지 마세요:

{{
  "summary": "오늘 운동 총평. 부상/회복 중이면 그 맥락 반영. 구체적 수치(페이스, 심박) 포함. 3~4문장.",
  "heartrate_analysis": "개인 심박존 기준으로 오늘 강도 평가. 구간별 심박 변화 언급. 목표 존 대비 실제 존 비교. 3문장.",
  "pace_analysis": "구간별 페이스 패턴 분석. 후반 페이스 변화, 일관성 평가. 개선 포인트 1가지 포함. 3문장.",
  "plan_vs_actual": "계획 대비 실제 거리/페이스/심박 수치 차이를 구체적으로 언급. 계획 없으면 null.",
  "progress": "과거 유사 운동 수치를 직접 인용해서 오늘과 비교. 개선/저하 여부 판단. 데이터 없으면 null."
}}"""

    logger.info(f"Ollama 분석 시작... (모델: {OLLAMA_MODEL})")
    text = await call_ollama(prompt, max_tokens=1000)
    logger.info("Ollama 분석 완료!")
    return text


