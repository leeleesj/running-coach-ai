import httpx
import app.config as config

async def get_activity(activity_id: int) -> dict:
    """
    Strava API로 운동 상세 데이터 가져오기
    
    acsess_token이 있어야 호출 가능
    6시간마다 만료되므로 나중에 refresh_token 로직 추가 필요
    """
    url = f"https://www.strava.com/api/v3/activities/{activity_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {config.STRAVA_ACCESS_TOKEN}"
            }
        )

    if response.status_code != 200:
        print(f"Strava API 에러: {response.status_code} {response.text}")
        return {}
    
    return response.json()

async def get_weekly_activities() -> list:
    """
    이번 주 활동 목록 가져오기
    after 파라미터로 이번 주 월요일 이후 활동만 필터링
    """
    from datetime import datetime, timedelta

    # 이번 주 월요일 00:00 타임스탬프
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    monday_ts = int(monday.replace(hour=0, minute=0, second=0).timestamp())

    url = "https://www.strava.com/api/v3/athlete/activities"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {config.STRAVA_ACCESS_TOKEN}"
            },
            params={
                "after": monday_ts,
                "per_page": 30  # 최대 30개 활동 가져오기
            }
        )

    if response.status_code != 200:
        print(f"Strava API 에러: {response.status_code} {response.text}")
        return []
    
    return response.json()


def parse_activity(raw: dict) -> dict:
    """
    Strava raw 데이터를 사람이 읽기 좋은 형태로 변환
    """

    def seconds_to_pace(speed_ms: float) -> str:
        """m/s → '분:초 /km' 변환"""
        if speed_ms <= 0:
            return "N/A"
        pace_sec = 1000 / speed_ms
        return f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d} /km"

    def seconds_to_time(seconds: int) -> str:
        """초 → '분:초' 변환"""
        return f"{seconds // 60}:{seconds % 60:02d}"

    # 기본 정보
    distance_km = round(raw.get("distance", 0) / 1000, 2)
    moving_time_sec = raw.get("moving_time", 0)

    # 페이스
    average_speed = raw.get("average_speed", 0)
    max_speed = raw.get("max_speed", 0)

    # 심박수
    avg_heartrate = raw.get("average_heartrate")
    max_heartrate = raw.get("max_heartrate")

    # 케이던스: API는 한발 기준 → 양발로 변환
    avg_cadence_raw = raw.get("average_cadence")
    avg_cadence = round(avg_cadence_raw * 2) if avg_cadence_raw else None

    # 고도
    elevation_gain = raw.get("total_elevation_gain", 0)
    elev_high = raw.get("elev_high")
    elev_low = raw.get("elev_low")

    # 날짜
    from datetime import datetime
    start_date_str = raw.get("start_date_local", "")
    try:
        dt = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%SZ")
        start_date_formatted = dt.strftime("%Y년 %-m월 %-d일 %H:%M")
    except:
        start_date_formatted = start_date_str

    # km별 구간 분석 (splits_metric)
    splits = []
    for s in raw.get("splits_metric", []):
        split_speed = s.get("average_speed", 0)
        splits.append({
            "km": s.get("split"),
            "pace": seconds_to_pace(split_speed),
            "avg_heartrate": round(s.get("average_heartrate", 0), 1),
            "moving_time": seconds_to_time(s.get("moving_time", 0)),
            "distance_m": round(s.get("distance", 0), 1),
        })

    # 역대 기록 순위
    similar = raw.get("similar_activities", {})
    pr_rank = similar.get("pr_rank")  # 1이면 역대 최고 페이스!

    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "type": raw.get("sport_type", "Run"),
        "date": start_date_formatted,
        "distance_km": distance_km,
        "moving_time": seconds_to_time(moving_time_sec),
        "moving_time_sec": moving_time_sec,
        "pace": seconds_to_pace(average_speed),
        "max_pace": seconds_to_pace(max_speed),
        "avg_heartrate": avg_heartrate,
        "max_heartrate": max_heartrate,
        "avg_cadence": avg_cadence,
        "calories": raw.get("calories", 0),
        "elevation_gain": elevation_gain,
        "elev_high": elev_high,
        "elev_low": elev_low,
        "splits": splits,
        "pr_rank": pr_rank,
        "manual": raw.get("manual", False),
    }