import httpx
import time
from datetime import datetime, timedelta

from app.core.logger import get_logger
from app.models.activity import ActivityData, SplitData
from app.models.database import get_user, update_tokens
import app.config as config

logger = get_logger(__name__)


async def refresh_access_token(athlete_id: int) -> str | None:
    """
    refresh_token으로 새 access_token 발급
    만료 10분 전에 미리 갱신
    """
    user = get_user(athlete_id)
    if not user:
        logger.warning(f"유저 없음: {athlete_id}")
        return None

    # 만료 10분 전부터 갱신 (600초)
    if user["token_expires_at"] > time.time() + 600:
        logger.debug("토큰 아직 유효함, 갱신 불필요")
        return user["access_token"]

    logger.info("토큰 만료 임박, 갱신 시작...")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": config.STRAVA_CLIENT_ID,
                "client_secret": config.STRAVA_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": user["refresh_token"],
            }
        )

    if response.status_code != 200:
        logger.error(f"토큰 갱신 실패: {response.status_code}")
        return None

    token_data = response.json()
    new_access_token = token_data["access_token"]
    new_refresh_token = token_data["refresh_token"]
    new_expires_at = token_data["expires_at"]

    update_tokens(athlete_id, new_access_token, new_refresh_token, new_expires_at)

    return new_access_token


async def get_activity(activity_id: int, athlete_id: int) -> dict:
    """
    access_token 자동 갱신 후 Strava API로 운동 상세 데이터 가져오기
    """
    access_token = await refresh_access_token(athlete_id)
    if not access_token:
        return {}

    url = f"https://www.strava.com/api/v3/activities/{activity_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"}
        )

    if response.status_code != 200:
        logger.error(f"Strava API 에러: {response.status_code} {response.text}")
        return {}

    return response.json()


async def get_weekly_activities(athlete_id: int) -> list:
    """
    이번 주 활동 목록 가져오기
    after 파라미터로 이번 주 월요일 이후 활동만 필터링
    """
    access_token = await refresh_access_token(athlete_id)
    if not access_token:
        return []

    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    monday_ts = int(monday.replace(hour=0, minute=0, second=0).timestamp())

    url = "https://www.strava.com/api/v3/athlete/activities"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "after": monday_ts,
                "per_page": 30,
            }
        )

    if response.status_code != 200:
        logger.error(f"Strava API 에러: {response.status_code} {response.text}")
        return []

    return response.json()


async def get_all_activities(athlete_id: int, per_page: int = 200) -> list:
    """
    전체 활동 히스토리 가져오기 (과거 데이터 동기화용)
    페이지네이션으로 모든 활동 조회
    과거→최신 순서로 반환
    """
    access_token = await refresh_access_token(athlete_id)
    if not access_token:
        return []

    url = "https://www.strava.com/api/v3/athlete/activities"
    all_activities = []
    page = 1

    async with httpx.AsyncClient() as client:
        while True:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "per_page": per_page,
                    "page": page,
                }
            )

            if response.status_code != 200:
                logger.error(f"Strava API 에러: {response.status_code} {response.text}")
                break

            activities = response.json()
            if not activities:
                break

            all_activities.extend(activities)
            logger.debug(f"페이지 {page}: {len(activities)}개 활동 가져옴 (누적: {len(all_activities)}개)")

            if len(activities) < per_page:
                break

            page += 1

    # 과거→최신 순서로 뒤집기 (시계열 저장)
    all_activities.reverse()

    logger.info(f"전체 활동 {len(all_activities)}개 가져오기 완료!")
    return all_activities


def parse_activity(raw: dict) -> ActivityData:
    """
    Strava raw 데이터를 ActivityData Pydantic 모델로 변환

    날짜:
    - date: ISO 형식 "2026-03-24T20:28:00" (정렬/계산/시계열 분석용)
    - date_display: 한국어 형식 "2026년 3월 24일 20:28" (텔레그램 표시용)
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

    def speed_to_pace_sec(speed_ms: float) -> float | None:
        """m/s → 초/km 변환"""
        if speed_ms <= 0:
            return None
        return round(1000 / speed_ms, 1)

    # 기본 정보
    distance_km = round(raw.get("distance", 0) / 1000, 2)
    moving_time_sec = raw.get("moving_time", 0)
    elapsed_time_sec = raw.get("elapsed_time", 0)

    # 페이스
    average_speed = raw.get("average_speed", 0)
    max_speed = raw.get("max_speed", 0)

    # 심박수 (원본만 저장, 보정값은 main.py에서 추가)
    avg_heartrate = raw.get("average_heartrate")
    max_heartrate = raw.get("max_heartrate")

    # 케이던스: API는 한발 기준 → 양발로 변환 (×2)
    avg_cadence_raw = raw.get("average_cadence")
    avg_cadence = round(avg_cadence_raw * 2) if avg_cadence_raw else None

    # 성과
    similar = raw.get("similar_activities", {})
    pr_rank = similar.get("pr_rank")
    trend = similar.get("trend", {})
    trend_direction = trend.get("direction")

    # 날짜 파싱
    start_date_str = raw.get("start_date_local", "")
    try:
        dt = datetime.strptime(start_date_str, "%Y-%m-%dT%H:%M:%SZ")
        # ISO 형식: 정렬/계산/시계열 분석용
        date_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")
        # 한국어 형식: 텔레그램 표시용
        date_display = dt.strftime("%Y년 %-m월 %-d일 %H:%M")
    except Exception:
        date_iso = start_date_str
        date_display = start_date_str

    # km별 구간 분석 (splits_metric)
    # 마지막 partial split (500m 미만) 제외 — 이상한 페이스 방지
    splits = []
    raw_splits = raw.get("splits_metric", [])
    for i, s in enumerate(raw_splits):
        distance_m = s.get("distance", 0)
        is_last = (i == len(raw_splits) - 1)
        if is_last and distance_m < 500:
            continue
        split_speed = s.get("average_speed", 0)
        grade_adjusted_speed = s.get("average_grade_adjusted_speed", 0)
        splits.append({
            "km": s.get("split"),
            "pace": seconds_to_pace(split_speed),
            "pace_sec": speed_to_pace_sec(split_speed),
            "avg_grade_adjusted_pace_sec": speed_to_pace_sec(grade_adjusted_speed),
            "avg_heartrate": round(s.get("average_heartrate", 0), 1),
            "moving_time": seconds_to_time(s.get("moving_time", 0)),
            "distance_m": round(distance_m, 1),
            "elevation_diff": s.get("elevation_difference", 0),
            "pace_zone": s.get("pace_zone"),
        })

    return ActivityData(
        id=raw.get("id"),
        name=raw.get("name"),
        type=raw.get("sport_type", "Run"),
        workout_type=raw.get("workout_type"),
        device_name=raw.get("device_name"),
        date=date_iso,           # ISO 형식 (DB 저장, 정렬용)
        date_display=date_display,  # 한국어 형식 (텔레그램 표시용)
        distance_km=distance_km,
        moving_time=seconds_to_time(moving_time_sec),
        moving_time_sec=moving_time_sec,
        elapsed_time_sec=elapsed_time_sec,
        pace=seconds_to_pace(average_speed),
        max_pace=seconds_to_pace(max_speed),
        avg_pace_sec=speed_to_pace_sec(average_speed),
        max_pace_sec=speed_to_pace_sec(max_speed),
        avg_heartrate=avg_heartrate,
        max_heartrate=max_heartrate,
        avg_cadence=avg_cadence,
        elevation_gain=raw.get("total_elevation_gain", 0),
        elev_high=raw.get("elev_high"),
        elev_low=raw.get("elev_low"),
        calories=raw.get("calories", 0),
        suffer_score=raw.get("suffer_score"),
        perceived_exertion=raw.get("perceived_exertion"),
        pr_count=raw.get("pr_count", 0),
        achievement_count=raw.get("achievement_count", 0),
        pr_rank=pr_rank,
        trend_direction=trend_direction,
        splits=[SplitData(**s) for s in splits],
        manual=raw.get("manual", False),
    )