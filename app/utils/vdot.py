"""
Jack Daniels VDOT 계산 모듈

VDOT: VO2max를 레이스 기록으로 추정한 단일 피트니스 지수
  - 레이스 기록 → VDOT 계산
  - VDOT → 훈련 페이스 처방 (E/M/T/I/R)
  - VDOT → 다른 거리 예상 기록

참고: Jack Daniels, "Daniels' Running Formula" (3rd ed.)
"""

import math


# 이벤트별 거리 (미터)
EVENT_DISTANCE = {
    "5km":  5000,
    "10km": 10000,
    "half": 21097.5,
    "full": 42195,
}


def calc_vdot(distance_m: float, time_sec: float) -> float:
    """
    레이스 기록으로 VDOT 계산
    distance_m: 거리 (미터)
    time_sec:   완주 시간 (초)
    반환: VDOT (소수점 1자리)
    """
    t = time_sec / 60  # 분 변환
    v = distance_m / t  # 속도 (m/min)

    # 산소 소비량 (ml/kg/min)
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v ** 2

    # VO2max 사용 비율
    pct = (0.8
           + 0.1894393 * math.exp(-0.012778 * t)
           + 0.2989558 * math.exp(-0.1932605 * t))

    return round(vo2 / pct, 1)


def calc_vdot_from_goal(event_type: str, target_time_sec: int) -> float | None:
    """
    Goals DB의 이벤트 타입과 목표 기록으로 VDOT 계산
    event_type: "5km" | "10km" | "half" | "full"
    """
    dist = EVENT_DISTANCE.get(event_type)
    if not dist or not target_time_sec:
        return None
    return calc_vdot(dist, target_time_sec)


def _velocity_from_pct(vdot: float, pct: float) -> float:
    """
    VDOT와 VO2max 사용 비율(pct)로 속도 계산 (m/min)
    VO2 = -4.60 + 0.182258*V + 0.000104*V² 를 역산
    """
    target_vo2 = pct * vdot
    # 0.000104*V² + 0.182258*V - (4.60 + target_vo2) = 0
    a = 0.000104
    b = 0.182258
    c = -(4.60 + target_vo2)
    v = (-b + math.sqrt(b ** 2 - 4 * a * c)) / (2 * a)
    return v


def _sec_per_km(velocity_m_per_min: float) -> int:
    """m/min → 초/km 변환"""
    return round(60000 / velocity_m_per_min)


def _fmt_pace(sec_per_km: int) -> str:
    """초/km → MM:SS/km 문자열"""
    return f"{sec_per_km // 60}:{sec_per_km % 60:02d}/km"


def get_training_paces(vdot: float) -> dict:
    """
    VDOT → 훈련 강도별 페이스 처방
    반환: {
        "E":  {"pct": (59,74),  "pace_range": "7:30~8:30/km", "pace_sec": (450,510), "description": "존2 조깅"},
        "M":  {...},
        "T":  {...},
        "I":  {...},
        "R":  {...},
    }

    강도별 VO2max 사용 비율 (Daniels 기준):
      E (Easy)       : 59~74%  → 존2 조깅 / LSD
      M (Marathon)   : 75~84%  → 마라톤 페이스
      T (Threshold)  : 83~88%  → 템포런
      I (Interval)   : 95~100% → 인터벌
      R (Repetition) : 105~120% → 레펫
    """
    zones = {
        "E": (0.59, 0.74, "존2 조깅 / LSD"),
        "M": (0.75, 0.84, "마라톤 페이스"),
        "T": (0.83, 0.88, "템포런"),
        "I": (0.95, 1.00, "인터벌"),
        "R": (1.05, 1.15, "레펫"),
    }

    result = {}
    for key, (lo, hi, desc) in zones.items():
        v_slow = _velocity_from_pct(vdot, lo)
        v_fast = _velocity_from_pct(vdot, hi)
        pace_slow = _sec_per_km(v_fast)  # 빠른 속도 = 빠른 페이스(낮은 숫자)
        pace_fast = _sec_per_km(v_slow)  # 느린 속도 = 느린 페이스(높은 숫자)
        result[key] = {
            "pace_range": f"{_fmt_pace(pace_slow)}~{_fmt_pace(pace_fast)}",
            "pace_sec_fast": pace_slow,
            "pace_sec_slow": pace_fast,
            "description": desc,
        }

    return result


def predict_race_time(vdot: float, distance_m: float) -> int:
    """
    VDOT + 거리 → 예상 완주 시간 (초)
    calc_vdot(distance, T) = vdot 를 이분탐색으로 역산
    """
    lo, hi = 60.0, 36000.0  # 1분 ~ 10시간 (초)
    for _ in range(60):
        mid = (lo + hi) / 2
        if calc_vdot(distance_m, mid) > vdot:
            lo = mid  # 너무 빠름 → 시간 늘리기
        else:
            hi = mid  # 너무 느림 → 시간 줄이기
    return round((lo + hi) / 2)


def predict_all_races(vdot: float) -> dict:
    """
    VDOT로 모든 주요 거리 예상 기록 계산
    반환: {"5km": "26:10", "10km": "54:20", "half": "2:00:30", "full": "4:12:00"}
    """
    result = {}
    for event, dist in EVENT_DISTANCE.items():
        sec = predict_race_time(vdot, dist)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h > 0:
            result[event] = f"{h}:{m:02d}:{s:02d}"
        else:
            result[event] = f"{m}:{s:02d}"
    return result


def vdot_level(vdot: float) -> str:
    """VDOT 구간별 레벨 설명"""
    if vdot < 30:
        return "입문"
    elif vdot < 35:
        return "초급"
    elif vdot < 40:
        return "중급"
    elif vdot < 45:
        return "중상급"
    elif vdot < 50:
        return "상급"
    elif vdot < 55:
        return "고급"
    else:
        return "엘리트"


def _fmt_time(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


def format_vdot_summary(
    event_type: str,
    target_time_sec: int,
    pb_time_sec: int = None,
) -> str:
    """
    주간/월간 코치 프롬프트용 VDOT 요약 텍스트
    - pb_time_sec 있으면 → PB 기반 훈련 페이스 처방
    - pb_time_sec 없으면 → target 기반 처방
    """
    # 훈련 페이스는 PB 기준 (현재 실력)
    base_sec = pb_time_sec if pb_time_sec else target_time_sec
    base_vdot = calc_vdot_from_goal(event_type, base_sec)
    target_vdot = calc_vdot_from_goal(event_type, target_time_sec)

    if not base_vdot:
        return ""

    paces = get_training_paces(base_vdot)
    predictions = predict_all_races(base_vdot)

    lines = [f"## VDOT 분석"]

    if pb_time_sec:
        lines += [
            f"- 현재 PB: {event_type} {_fmt_time(pb_time_sec)} → VDOT {base_vdot} ({vdot_level(base_vdot)})",
            f"- 목표:    {event_type} {_fmt_time(target_time_sec)} → VDOT {target_vdot} ({vdot_level(target_vdot)}) (차이 +{round(target_vdot - base_vdot, 1)}p)",
        ]
    else:
        lines += [
            f"- VDOT: {base_vdot} ({vdot_level(base_vdot)}) (PB 미입력 → 목표기록 기준)",
        ]

    lines += [
        f"- 현재 기준 예상: 5km {predictions['5km']} | 10km {predictions['10km']} | 하프 {predictions['half']}",
        f"",
        f"## VDOT 기반 훈련 페이스 처방 (현재 실력 기준)",
        f"- 존2 조깅 (E): {paces['E']['pace_range']}",
        f"- 마라톤 페이스 (M): {paces['M']['pace_range']}",
        f"- 템포런 (T): {paces['T']['pace_range']}",
        f"- 인터벌 (I): {paces['I']['pace_range']}",
    ]
    return "\n".join(lines)
