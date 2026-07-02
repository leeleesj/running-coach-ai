"""Apple Health 데이터 파싱 (iPhone Shortcuts → FastAPI)"""

from datetime import datetime
from app.models.activity import ActivityData


def _fmt_pace(pace_sec: float) -> str:
    if not pace_sec or pace_sec <= 0:
        return "-"
    m = int(pace_sec // 60)
    s = int(pace_sec % 60)
    return f"{m}:{s:02d}/km"


def _fmt_moving_time(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"


def parse_apple_health(data: dict) -> ActivityData:
    """
    iPhone Shortcuts가 전송한 Apple Health JSON → ActivityData 변환

    입력 JSON 형식:
    {
        "source": "apple_health",
        "name": "Morning Run",
        "start_date": "2026-07-02T06:30:00",
        "duration_sec": 2700,
        "distance_m": 8050.5,
        "calories": 612,
        "avg_heartrate": 148.0,
        "max_heartrate": 172.0,
        "elevation_gain": 34.0,
        "avg_cadence": null,
        "splits": []
    }
    """
    start_date_str = data.get("start_date", "")
    dt = datetime.fromisoformat(start_date_str)

    # ISO 형식 (DB/정렬용)
    date_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
    # 한국어 형식 (표시용)
    date_display = dt.strftime("%Y년 %-m월 %-d일 %H:%M")

    # 합성 ID: -unix_timestamp → Strava ID(양수)와 절대 충돌 없음
    synthetic_id = -int(dt.timestamp())

    distance_m = float(data.get("distance_m") or 0)
    distance_km = round(distance_m / 1000, 2)

    duration_sec = int(data.get("duration_sec") or 0)

    # 평균 페이스 계산
    avg_pace_sec = round(duration_sec / distance_km, 1) if distance_km > 0 else 0

    return ActivityData(
        id=synthetic_id,
        name=data.get("name") or "러닝",
        type="Run",
        date=date_iso,
        date_display=date_display,
        distance_km=distance_km,
        moving_time=_fmt_moving_time(duration_sec),
        moving_time_sec=duration_sec,
        pace=_fmt_pace(avg_pace_sec),
        max_pace=_fmt_pace(avg_pace_sec),  # Apple Health는 최고 페이스 미제공
        avg_pace_sec=avg_pace_sec,
        avg_heartrate=data.get("avg_heartrate"),
        max_heartrate=data.get("max_heartrate"),
        avg_cadence=data.get("avg_cadence"),
        elevation_gain=float(data.get("elevation_gain") or 0),
        calories=float(data.get("calories") or 0),
        splits=[],  # Apple Health는 km 구간 데이터 미제공
    )
