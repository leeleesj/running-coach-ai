"""
주간 코치 (P1-04)

매주 월요일 아침 실행:
  1. Notion 목표/프로필 동기화
  2. ACWR 계산 → 적정 주간 부하 산출
  3. 목표 대비 훈련 단계 판단 (베이스/빌드/피크/테이퍼)
  4. Qwen으로 7일 스케줄 생성 → DB 저장
  5. Notion 주간 계획 DB 기록
  6. 텔레그램 발송
"""

import json
import httpx
from datetime import datetime, timedelta

from app.core.logger import get_logger
logger = get_logger(__name__)

from app.models.database import (
    get_active_goals, get_training_zones, calculate_acwr,
    save_weekly_plan, get_weekly_plan_by_date, get_current_weekly_plan,
)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:14b-ctx8k"

DAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
DAY_KEY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _get_training_phase(goals: list, weeks_ahead: int = 0) -> str:
    """
    가장 가까운 확정 대회까지 남은 주 수로 훈련 단계 판단
    대회 미확정이면 현재 날짜 기준으로 추정
    """
    now = datetime.now() + timedelta(weeks=weeks_ahead)

    # 가장 가까운 확정 대회 찾기
    nearest_days = None
    for g in goals:
        if g.get("target_date") and g.get("race_confirmed"):
            target = datetime.fromisoformat(g["target_date"])
            days_left = (target - now).days
            if days_left > 0:
                if nearest_days is None or days_left < nearest_days:
                    nearest_days = days_left

    if nearest_days is None:
        # 대회 미확정: 목표 달성까지 넉넉하게 베이스/빌드 반복
        week_of_year = now.isocalendar()[1]
        return "build" if week_of_year % 4 in (1, 2) else "base"

    weeks_left = nearest_days // 7
    if weeks_left <= 1:
        return "taper"
    elif weeks_left <= 3:
        return "peak"
    elif weeks_left <= 7:
        return "build"
    else:
        return "base"


def _format_goal_text(goals: list) -> str:
    """목표 텍스트 생성"""
    if not goals:
        return "목표 미설정 (기본 건강 달리기)"

    lines = []
    for g in goals:
        sec = g.get("target_time_sec", 0)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
        race_info = f" ({g['race_name']} {g['target_date']})" if g.get("race_confirmed") and g.get("race_name") else ""
        priority_kr = "주요" if g["priority"] == "primary" else "보조"
        lines.append(f"{priority_kr} - {g['event_type']} {time_str}{race_info}")

    return "\n".join(lines)


async def generate_weekly_plan(user_id: int = 1) -> dict | None:
    """
    주간 계획 생성 메인 함수
    반환: { week_start, phase, sessions, total_planned_km, weekly_comment }
    """
    # 1. 목표 + 존 + ACWR 조회
    goals = get_active_goals(user_id)
    zones = get_training_zones(user_id)
    acwr_data = calculate_acwr(user_id)

    # 3. 이번 주 월요일 날짜
    now = datetime.now()
    days_since_monday = now.weekday()
    monday = now - timedelta(days=days_since_monday)
    week_start = monday.strftime("%Y-%m-%d")

    # 이미 이번 주 계획이 있으면 스킵
    existing = get_weekly_plan_by_date(week_start)
    if existing and existing.get("plan_json"):
        logger.info(f"이번 주 계획 이미 존재: {week_start}")
        return json.loads(existing["plan_json"])

    # 4. 훈련 단계 판단
    phase = _get_training_phase(goals)
    phase_kr = {"base": "베이스", "build": "빌드", "peak": "피크", "taper": "테이퍼"}.get(phase, phase)

    # 5. 날짜 목록 (월~일)
    dates = [(monday + timedelta(days=i)).strftime("%m/%d") for i in range(7)]

    # 6. 목표에서 훈련 가능 일수 / 최대 거리 추출
    primary_goal = next((g for g in goals if g["priority"] == "primary"), None)
    available_days = primary_goal["weekly_days_available"] if primary_goal else 4
    max_km = primary_goal["max_weekly_km"] if primary_goal else 30
    injury_notes = primary_goal.get("injury_notes", "") if primary_goal else ""

    # 7. VDOT 계산 (primary 목표 기반)
    vdot_text = ""
    vdot_value = None
    paces = {}
    if primary_goal:
        from app.utils.vdot import calc_vdot_from_goal, format_vdot_summary, get_training_paces
        pb_sec = primary_goal.get("pb_time_sec") or primary_goal.get("target_time_sec", 0)
        vdot_value = calc_vdot_from_goal(
            primary_goal.get("event_type", ""),
            pb_sec,
        )
        if vdot_value:
            paces = get_training_paces(vdot_value)
            vdot_text = "\n" + format_vdot_summary(
                event_type=primary_goal["event_type"],
                target_time_sec=primary_goal["target_time_sec"],
                pb_time_sec=primary_goal.get("pb_time_sec"),
            ) + "\n"

    # 8. Qwen 프롬프트 생성
    # 부상 시 제약 텍스트 (LLM이 자연어로 판단)
    injury_block = ""
    if injury_notes:
        injury_block = f"""
⛔ 부상 주의 (최우선 적용)
- 부상 상태: {injury_notes}
- 부상 메모를 읽고 훈련 가능 수준을 스스로 판단할 것
- 뛰지 말아야 할 상황(골절/수술/완전 휴식 등)이면 모든 세션을 휴식으로 설정
- 가볍게 뛸 수 있는 상황이면 존2 조깅 / 회복 조깅 / 휴식만 사용
- 어떤 경우에도 인터벌 / 템포런 / LSD는 포함 금지
- total_planned_km는 반드시 {max_km}km 이하로 제한
"""

    prompt = f"""당신은 전문 러닝 코치입니다. 이번 주 7일 훈련 계획을 JSON으로 작성해주세요.
{injury_block}
## 훈련 목표
{_format_goal_text(goals)}
{vdot_text}
## 현재 상태
- 훈련 단계: {phase_kr}
- ACWR: {acwr_data['acwr']} (최근 7일 {acwr_data['acute_km']}km / 4주 주간평균 {acwr_data['chronic_weekly_km']}km)

## 개인 심박존
존1: ~{zones['zone1_max']}bpm
존2: {zones['zone1_max']+1}~{zones['zone2_max']}bpm (유산소 기반)
존3: {zones['zone2_max']+1}~{zones['zone3_max']}bpm (유산소 파워)
존4: {zones['zone3_max']+1}~{zones['zone4_max']}bpm (무산소 역치)

## 훈련 제약
- 주당 훈련 가능 일수: {available_days}일
- 주당 최대 거리: {max_km}km (반드시 준수)
- ACWR 안전 범위: 0.8~1.3 (현재 {acwr_data['acwr']} → {acwr_data['risk']})
{"⚠️ ACWR이 1.3 초과: 부상 위험 높음. total_planned_km는 반드시 최근 7일(" + str(acwr_data['acute_km']) + "km) 이하." if acwr_data['acwr'] > 1.3 else ""}

## 이번 주 날짜
월({dates[0]}), 화({dates[1]}), 수({dates[2]}), 목({dates[3]}), 금({dates[4]}), 토({dates[5]}), 일({dates[6]})

## 훈련 단계별 지침 (부상 없을 때만 적용)
- 베이스: 존2 비율 70%+, LSD 포함, 강도 낮게
- 빌드: 템포런/인터벌 추가, 주간 거리 점진 증가
- 피크: 최고 강도+거리, 레이스페이스 포함
- 테이퍼: 거리 50% 감소, 강도 유지, 레이스 준비

## 응답 형식
반드시 아래 JSON만 응답하세요:

{{
  "phase": "{phase}",
  "sessions": {{
    "mon": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "tue": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "wed": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "thu": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "fri": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "sat": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}},
    "sun": {{"type": "훈련종류", "distance_km": 숫자, "pace": "페이스범위", "heartrate": "심박범위", "notes": "메모"}}
  }},
  "total_planned_km": 숫자,
  "weekly_comment": "이번 주 훈련 방향 한 줄"
}}

훈련종류는 반드시: 존2 조깅 / 템포런 / 인터벌 / LSD / 회복 조깅 / 휴식 중 하나
휴식인 경우 distance_km=0, pace="-", heartrate="-"
"""

    logger.info(f"주간 계획 생성 중... (단계: {phase_kr}, ACWR: {acwr_data['acwr']})")

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 800, "temperature": 0.5},
            }
        )

    if resp.status_code != 200:
        logger.error(f"Ollama 에러: {resp.status_code}")
        return None

    raw = resp.json().get("response", "")

    # JSON 파싱
    import re
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    try:
        plan = json.loads(raw.strip())
    except Exception as e:
        logger.error(f"주간 계획 JSON 파싱 실패: {e}\n{raw[:300]}")
        return None

    # 날짜 정보 + VDOT 추가
    plan["week_start"] = week_start
    plan["dates"] = {key: (monday + timedelta(days=i)).strftime("%Y-%m-%d")
                     for i, key in enumerate(DAY_KEY)}
    if vdot_value:
        plan["vdot"] = vdot_value

    # max_km 상한 항상 강제 (부상 여부 무관)
    total = sum(s.get("distance_km", 0) for s in plan.get("sessions", {}).values())
    plan["total_planned_km"] = min(round(total, 1), max_km)
    if total > max_km:
        logger.info(f"총 거리 상한 클리핑: {round(total,1)}km → {plan['total_planned_km']}km")

    # DB 저장
    save_weekly_plan(
        user_id=user_id,
        week_start=week_start,
        plan_json=json.dumps(plan, ensure_ascii=False),
        total_planned_km=plan.get("total_planned_km", 0),
        phase=phase,
        acwr=acwr_data["acwr"],
    )

    logger.info(f"주간 계획 생성 완료: {week_start} ({phase_kr}, {plan.get('total_planned_km')}km)")
    return plan


def get_today_planned_session(plan: dict) -> dict | None:
    """오늘 요일에 해당하는 계획 세션 반환"""
    if not plan:
        return None
    day_key = DAY_KEY[datetime.now().weekday()]
    return plan.get("sessions", {}).get(day_key)


def get_tomorrow_planned_session(plan: dict) -> dict | None:
    """내일 요일에 해당하는 계획 세션 반환"""
    if not plan:
        return None
    tomorrow_idx = (datetime.now().weekday() + 1) % 7
    day_key = DAY_KEY[tomorrow_idx]
    return plan.get("sessions", {}).get(day_key)


def format_weekly_plan_message(plan: dict) -> str:
    """주간 계획 텔레그램 메시지 포맷"""
    if not plan:
        return "주간 계획 생성 실패"

    phase_kr = {"base": "베이스", "build": "빌드", "peak": "피크", "taper": "테이퍼"}.get(
        plan.get("phase", ""), plan.get("phase", "")
    )
    week_start = plan.get("week_start", "")
    total_km = plan.get("total_planned_km", 0)
    comment = plan.get("weekly_comment", "")

    lines = [
        f"📅 이번 주 훈련 계획 ({week_start}~)",
        f"단계: {phase_kr} | 목표 거리: {total_km}km",
        f"{comment}",
        "",
    ]

    sessions = plan.get("sessions", {})
    dates = plan.get("dates", {})

    for i, (key, kr) in enumerate(zip(DAY_KEY, DAY_KR)):
        s = sessions.get(key, {})
        date_str = dates.get(key, "")
        date_display = f"{date_str[5:]}".replace("-", "/") if date_str else ""
        s_type = s.get("type", "휴식")

        if s_type == "휴식" or s.get("distance_km", 0) == 0:
            lines.append(f"{kr}({date_display}) 휴식")
        else:
            dist = s.get("distance_km", 0)
            pace = s.get("pace", "-")
            hr = s.get("heartrate", "-")
            hr_str = str(hr).replace("bpm", "").strip()
            lines.append(f"{kr}({date_display}) {s_type} {dist}km | {pace} | {hr_str}bpm")

    return "\n".join(lines)
