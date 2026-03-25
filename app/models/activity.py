from pydantic import BaseModel, Field
from typing import Optional


class SplitData(BaseModel):
    """km별 구간 데이터"""
    km: int
    pace: str
    pace_sec: Optional[float] = None
    avg_grade_adjusted_pace_sec: Optional[float] = None
    avg_heartrate: float
    moving_time: str
    distance_m: float
    elevation_diff: Optional[float] = None
    pace_zone: Optional[int] = None


class ActivityData(BaseModel):
    """Strava 운동 데이터 파싱 결과"""

    # 기본 정보
    id: int
    name: str
    type: str = "Run"
    workout_type: Optional[int] = None
    device_name: Optional[str] = None
    date: str

    # 거리/시간
    distance_km: float
    moving_time: str
    moving_time_sec: int
    elapsed_time_sec: Optional[int] = None

    # 페이스
    pace: str
    max_pace: str
    avg_pace_sec: Optional[float] = None
    max_pace_sec: Optional[float] = None

    # 심박수 (원본)
    avg_heartrate: Optional[float] = None
    max_heartrate: Optional[float] = None

    # 심박수 (보정값 - main.py에서 추가)
    avg_heartrate_adjusted: Optional[float] = None
    hr_correction: Optional[float] = None
    hr_correction_comment: Optional[str] = None

    # 케이던스
    avg_cadence: Optional[int] = None

    # 고도
    elevation_gain: float = 0
    elev_high: Optional[float] = None
    elev_low: Optional[float] = None

    # 칼로리/피로
    calories: float = 0
    suffer_score: Optional[int] = None
    perceived_exertion: Optional[int] = None

    # 성과
    pr_count: int = 0
    achievement_count: int = 0
    pr_rank: Optional[int] = None
    trend_direction: Optional[int] = None

    # 구간 데이터
    splits: list[SplitData] = Field(default_factory=list)

    # 기타
    manual: bool = False