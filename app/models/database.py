import sqlite3
import json
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from app.models.activity import ActivityData, SplitData

# DB 파일 경로
DB_PATH = Path("data/running_coach.db")


def get_connection():
    """DB 연결 반환. Row를 딕셔너리로 접근 가능하게 설정"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """테이블 생성. 서버 시작 시 한 번 실행"""
    DB_PATH.parent.mkdir(exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strava_athlete_id INTEGER UNIQUE NOT NULL,
            name TEXT,
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            strava_id INTEGER UNIQUE NOT NULL,

            -- 기본 정보
            name TEXT,
            type TEXT DEFAULT 'Run',
            workout_type INTEGER,
            device_name TEXT,
            date TEXT,

            -- 거리/시간
            distance_km REAL,
            moving_time INTEGER,
            elapsed_time INTEGER,

            -- 페이스
            avg_pace_sec REAL,
            max_pace_sec REAL,

            -- 심박수 (원본 vs 보정)
            avg_heartrate REAL,
            max_heartrate REAL,
            avg_heartrate_adjusted REAL,
            hr_correction REAL,
            hr_correction_comment TEXT,

            -- 케이던스
            avg_cadence INTEGER,

            -- 고도
            elevation_gain REAL,
            elev_high REAL,
            elev_low REAL,

            -- 칼로리/피로
            calories REAL,
            suffer_score INTEGER,
            perceived_exertion INTEGER,

            -- 성과
            pr_count INTEGER,
            achievement_count INTEGER,
            pr_rank_similar INTEGER,
            trend_direction INTEGER,

            -- AI 분석 (Phase 2)
            training_type TEXT,
            fatigue_score INTEGER,
            ai_analysis_json TEXT,

            -- 원본 데이터
            splits_json TEXT,
            raw_json TEXT,

            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER REFERENCES activities(id),
            km INTEGER,
            pace_sec REAL,
            avg_grade_adjusted_pace_sec REAL,
            heartrate REAL,
            distance_m REAL,
            elevation_diff REAL,
            pace_zone INTEGER
        );

        CREATE TABLE IF NOT EXISTS training_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            zone1_max INTEGER DEFAULT 138,
            zone2_max INTEGER DEFAULT 150,
            zone3_max INTEGER DEFAULT 162,
            zone4_max INTEGER DEFAULT 174,
            zone5_max INTEGER DEFAULT 999,
            max_heartrate INTEGER DEFAULT 187,
            resting_heartrate INTEGER DEFAULT 67,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- 훈련 목표 (복수 목표 지원)
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            priority TEXT DEFAULT 'primary',   -- 'primary' / 'secondary'
            event_type TEXT,                   -- '10km' / 'half' / 'full'
            target_time_sec INTEGER,           -- 목표 기록 (초)
            pb_time_sec INTEGER,               -- 현재 PB (초), VDOT 훈련 페이스 기준
            target_date TEXT,                  -- nullable, 대회 날짜
            race_name TEXT,                    -- nullable, 대회명
            race_confirmed INTEGER DEFAULT 0,  -- 0/1
            status TEXT DEFAULT 'active',      -- 'active' / 'achieved' / 'abandoned'
            weekly_days_available INTEGER DEFAULT 4,
            max_weekly_km REAL DEFAULT 30,
            injury_notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- 주간 훈련 계획 (매주 월요일 생성)
        CREATE TABLE IF NOT EXISTS weekly_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            week_start TEXT UNIQUE,            -- ISO (월요일 날짜 YYYY-MM-DD)
            plan_json TEXT,                    -- 7일 스케줄 JSON
            total_planned_km REAL,
            phase TEXT,                        -- 'base' / 'build' / 'peak' / 'taper'
            acwr REAL,                         -- 생성 시점 ACWR
            adherence_rate REAL,               -- 주 종료 후 업데이트 (%)
            generated_at TEXT DEFAULT (datetime('now')),
            notion_page_id TEXT                -- Notion에 기록된 페이지 ID
        );

        -- 월간 리포트 (매월 1일 생성)
        CREATE TABLE IF NOT EXISTS monthly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            year_month TEXT UNIQUE,            -- 'YYYY-MM'
            total_km REAL,
            total_sessions INTEGER,
            adherence_rate REAL,
            zone_distribution TEXT,            -- JSON {존1: %, 존2: %, ...}
            fitness_assessment TEXT,           -- AI 평가 텍스트
            goal_progress TEXT,               -- 목표 대비 진행률 텍스트
            generated_at TEXT DEFAULT (datetime('now')),
            notion_page_id TEXT
        );

        -- 주간 점수 히스토리 (대시보드 그래프용)
        CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            week_start TEXT UNIQUE,             -- 월요일 날짜 YYYY-MM-DD
            vdot REAL,
            fitness_score INTEGER,              -- CTL 기반 0~100
            efficiency_score INTEGER,           -- 심박 효율 0~100
            compliance_score INTEGER,           -- 이행률 0~100
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- 신체 정보 히스토리
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            height_cm REAL,
            weight_kg REAL,
            recorded_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # 기존 테이블에 새 컬럼 추가 (마이그레이션)
    migrations = [
        "ALTER TABLE activities ADD COLUMN training_type TEXT",
        "ALTER TABLE activities ADD COLUMN fatigue_score INTEGER",
        "ALTER TABLE activities ADD COLUMN ai_analysis_json TEXT",
        "ALTER TABLE activities ADD COLUMN workout_type INTEGER",
        "ALTER TABLE activities ADD COLUMN device_name TEXT",
        "ALTER TABLE activities ADD COLUMN elapsed_time INTEGER",
        "ALTER TABLE activities ADD COLUMN max_pace_sec REAL",
        "ALTER TABLE activities ADD COLUMN avg_heartrate_adjusted REAL",
        "ALTER TABLE activities ADD COLUMN hr_correction REAL",
        "ALTER TABLE activities ADD COLUMN hr_correction_comment TEXT",
        "ALTER TABLE activities ADD COLUMN elev_high REAL",
        "ALTER TABLE activities ADD COLUMN elev_low REAL",
        "ALTER TABLE activities ADD COLUMN suffer_score INTEGER",
        "ALTER TABLE activities ADD COLUMN perceived_exertion INTEGER",
        "ALTER TABLE activities ADD COLUMN pr_count INTEGER",
        "ALTER TABLE activities ADD COLUMN achievement_count INTEGER",
        "ALTER TABLE activities ADD COLUMN pr_rank_similar INTEGER",
        "ALTER TABLE activities ADD COLUMN trend_direction INTEGER",
        "ALTER TABLE splits ADD COLUMN avg_grade_adjusted_pace_sec REAL",
        "ALTER TABLE splits ADD COLUMN elevation_diff REAL",
        "ALTER TABLE splits ADD COLUMN pace_zone INTEGER",
    ]
    for migration in migrations:
        try:
            cursor.execute(migration)
        except Exception:
            pass

    # 마이그레이션: 기존 DB에 없는 컬럼 추가
    try:
        cursor.execute("ALTER TABLE monthly_reports ADD COLUMN next_month_focus TEXT")
        conn.commit()
        logger.info("마이그레이션: monthly_reports.next_month_focus 컬럼 추가")
    except Exception:
        pass  # 이미 존재하면 무시

    conn.commit()
    conn.close()
    logger.info("DB 초기화 완료!")


def get_training_zones(user_id: int = 1) -> dict:
    """
    유저의 훈련존 데이터 가져오기
    없으면 애플워치 기반 기본값 반환
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM training_zones WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "zone1_max": row["zone1_max"],
            "zone2_max": row["zone2_max"],
            "zone3_max": row["zone3_max"],
            "zone4_max": row["zone4_max"],
            "zone5_max": row["zone5_max"],
            "max_heartrate": row["max_heartrate"],
            "resting_heartrate": row["resting_heartrate"],
        }

    # DB에 없으면 애플워치 기반 기본값
    return {
        "zone1_max": 138,
        "zone2_max": 150,
        "zone3_max": 162,
        "zone4_max": 174,
        "zone5_max": 999,
        "max_heartrate": 187,
        "resting_heartrate": 67,
    }


def get_zone_for_heartrate(heartrate: float, zones: dict) -> str:
    """
    심박수로 존 이름 반환
    프롬프트에서 "오늘 평균 심박은 존X입니다" 표현에 활용
    """
    if heartrate <= zones["zone1_max"]:
        return "존1 (매우 가벼움)"
    elif heartrate <= zones["zone2_max"]:
        return "존2 (유산소 기반)"
    elif heartrate <= zones["zone3_max"]:
        return "존3 (유산소 파워)"
    elif heartrate <= zones["zone4_max"]:
        return "존4 (무산소 역치)"
    else:
        return "존5 (최대 강도)"


def save_activity(parsed: "ActivityData", user_id: int = 1) -> int:
    """
    ActivityData Pydantic 모델을 DB에 저장
    이미 저장된 strava_id면 업데이트, 없으면 새로 삽입 (upsert)
    """
    logger.debug(f"저장할 데이터: id={parsed.id}, name={parsed.name}")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO activities (
            user_id, strava_id, name, type, workout_type, device_name, date,
            distance_km, moving_time, elapsed_time, avg_pace_sec, max_pace_sec,
            avg_heartrate, max_heartrate, avg_heartrate_adjusted,
            hr_correction, hr_correction_comment,
            avg_cadence, elevation_gain, elev_high, elev_low,
            calories, suffer_score, perceived_exertion,
            pr_count, achievement_count, pr_rank_similar, trend_direction,
            splits_json, raw_json
        ) VALUES (
            ?,?,?,?,?,?,?,
            ?,?,?,?,?,
            ?,?,?,
            ?,?,
            ?,?,?,?,
            ?,?,?,
            ?,?,?,?,
            ?,?
        )
        ON CONFLICT(strava_id) DO UPDATE SET
            name=excluded.name,
            avg_heartrate=excluded.avg_heartrate,
            max_heartrate=excluded.max_heartrate,
            avg_heartrate_adjusted=excluded.avg_heartrate_adjusted,
            hr_correction=excluded.hr_correction,
            hr_correction_comment=excluded.hr_correction_comment,
            calories=excluded.calories,
            suffer_score=excluded.suffer_score,
            perceived_exertion=excluded.perceived_exertion,
            pr_count=excluded.pr_count,
            achievement_count=excluded.achievement_count,
            pr_rank_similar=excluded.pr_rank_similar,
            trend_direction=excluded.trend_direction,
            splits_json=excluded.splits_json,
            raw_json=excluded.raw_json
    """, (
        user_id,
        parsed.id,
        parsed.name,
        parsed.type,
        parsed.workout_type,
        parsed.device_name,
        parsed.date,
        parsed.distance_km,
        parsed.moving_time_sec,
        parsed.elapsed_time_sec,
        parsed.avg_pace_sec,
        parsed.max_pace_sec,
        parsed.avg_heartrate,
        parsed.max_heartrate,
        parsed.avg_heartrate_adjusted,
        parsed.hr_correction,
        parsed.hr_correction_comment,
        parsed.avg_cadence,
        parsed.elevation_gain,
        parsed.elev_high,
        parsed.elev_low,
        parsed.calories,
        parsed.suffer_score,
        parsed.perceived_exertion,
        parsed.pr_count,
        parsed.achievement_count,
        parsed.pr_rank,
        parsed.trend_direction,
        json.dumps([s.model_dump() for s in parsed.splits], ensure_ascii=False),
        "{}",
    ))

    conn.commit()

    cursor.execute(
        "SELECT id FROM activities WHERE strava_id = ?",
        (parsed.id,)
    )
    row = cursor.fetchone()
    activity_db_id = row["id"] if row else 0
    conn.close()

    logger.info(f"DB 저장 완료! db_id={activity_db_id}")
    return activity_db_id


def update_activity_analysis(activity_db_id: int, analysis_dict: dict) -> None:
    """LLM 분석 결과를 activities.ai_analysis_json에 저장"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE activities SET ai_analysis_json = ? WHERE id = ?",
        (json.dumps(analysis_dict, ensure_ascii=False), activity_db_id)
    )
    conn.commit()
    conn.close()


def classify_training_type(avg_heartrate: float, distance_km: float, zones: dict) -> str:
    """심박/거리 기반 훈련 종류 자동 분류"""
    if not avg_heartrate:
        return "러닝"
    z1 = zones["zone1_max"]
    z2 = zones["zone2_max"]
    z3 = zones["zone3_max"]

    if avg_heartrate <= z1:
        return "회복 조깅"
    elif avg_heartrate <= z2:
        return "LSD" if distance_km >= 15 else "존2 조깅"
    elif avg_heartrate <= z3:
        return "템포런"
    else:
        return "인터벌"


def update_activity_training_type(activity_db_id: int, training_type: str) -> None:
    """activities.training_type 업데이트"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE activities SET training_type = ? WHERE id = ?",
        (training_type, activity_db_id)
    )
    conn.commit()
    conn.close()


def save_splits(activity_db_id: int, splits: list) -> None:
    """
    SplitData Pydantic 모델 리스트를 splits 테이블에 저장
    activity_db_id: activities 테이블의 id (strava_id 아님)
    """
    if not splits:
        return

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM splits WHERE activity_id = ?", (activity_db_id,))

    for split in splits:
        if hasattr(split, "km"):
            cursor.execute("""
                INSERT INTO splits (
                    activity_id, km, pace_sec, avg_grade_adjusted_pace_sec,
                    heartrate, distance_m, elevation_diff, pace_zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                activity_db_id,
                split.km,
                split.pace_sec,
                split.avg_grade_adjusted_pace_sec,
                split.avg_heartrate,
                split.distance_m,
                split.elevation_diff,
                split.pace_zone,
            ))
        else:
            cursor.execute("""
                INSERT INTO splits (
                    activity_id, km, pace_sec, avg_grade_adjusted_pace_sec,
                    heartrate, distance_m, elevation_diff, pace_zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                activity_db_id,
                split.get("km"),
                split.get("pace_sec"),
                split.get("avg_grade_adjusted_pace_sec"),
                split.get("avg_heartrate"),
                split.get("distance_m"),
                split.get("elevation_diff"),
                split.get("pace_zone"),
            ))

    conn.commit()
    conn.close()
    logger.debug(f"splits 저장 완료! {len(splits)}개 구간")


def save_user(athlete_id: int, name: str, access_token: str,
              refresh_token: str, expires_at: int) -> int:
    """유저 저장 또는 업데이트 (upsert)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (
            strava_athlete_id, name, access_token, refresh_token, token_expires_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(strava_athlete_id) DO UPDATE SET
            access_token=excluded.access_token,
            refresh_token=excluded.refresh_token,
            token_expires_at=excluded.token_expires_at
    """, (athlete_id, name, access_token, refresh_token, expires_at))

    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    logger.info(f"유저 저장 완료! athlete_id={athlete_id}")
    return user_id


def get_user(athlete_id: int) -> dict | None:
    """유저 정보 가져오기"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE strava_athlete_id = ?",
        (athlete_id,)
    )
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def update_tokens(athlete_id: int, access_token: str,
                  refresh_token: str, expires_at: int):
    """토큰 갱신 후 DB 업데이트"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users SET
            access_token = ?,
            refresh_token = ?,
            token_expires_at = ?
        WHERE strava_athlete_id = ?
    """, (access_token, refresh_token, expires_at, athlete_id))

    conn.commit()
    conn.close()
    logger.info(f"토큰 갱신 완료! expires_at={expires_at}")


# ── Goals ────────────────────────────────────────────────────────────────────

def get_active_goals(user_id: int = 1) -> list[dict]:
    """활성 목표 목록 반환 (priority 순)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM goals WHERE user_id = ? AND status = 'active' ORDER BY priority ASC",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_goal(user_id: int, priority: str, event_type: str,
                target_time_sec: int, pb_time_sec: int = None,
                target_date: str = None, race_name: str = None,
                race_confirmed: bool = False, weekly_days_available: int = 4,
                max_weekly_km: float = 30, injury_notes: str = None) -> int:
    """목표 저장 (같은 priority + event_type이면 업데이트)"""
    conn = get_connection()
    cursor = conn.cursor()

    # 기존 DB 마이그레이션 (컬럼/인덱스 없으면 추가)
    try:
        cursor.execute("ALTER TABLE goals ADD COLUMN pb_time_sec INTEGER")
        conn.commit()
    except Exception:
        pass
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_goals_unique
            ON goals (user_id, priority, event_type, status)
        """)
        conn.commit()
    except Exception:
        pass

    cursor.execute("""
        INSERT INTO goals (
            user_id, priority, event_type, target_time_sec, pb_time_sec,
            target_date, race_name, race_confirmed, weekly_days_available,
            max_weekly_km, injury_notes, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT DO NOTHING
    """, (user_id, priority, event_type, target_time_sec, pb_time_sec,
          target_date, race_name, 1 if race_confirmed else 0,
          weekly_days_available, max_weekly_km, injury_notes))

    # 이미 있으면 업데이트
    cursor.execute("""
        UPDATE goals SET
            target_time_sec = ?, pb_time_sec = ?, target_date = ?,
            race_name = ?, race_confirmed = ?, weekly_days_available = ?,
            max_weekly_km = ?, injury_notes = ?, updated_at = datetime('now')
        WHERE user_id = ? AND priority = ? AND event_type = ? AND status = 'active'
    """, (target_time_sec, pb_time_sec, target_date, race_name,
          1 if race_confirmed else 0, weekly_days_available, max_weekly_km,
          injury_notes, user_id, priority, event_type))

    conn.commit()
    goal_id = cursor.lastrowid
    conn.close()
    return goal_id


# ── Weekly Plans ─────────────────────────────────────────────────────────────

def get_current_weekly_plan(user_id: int = 1) -> dict | None:
    """이번 주(가장 최근) 주간 계획 반환"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM weekly_plans WHERE user_id = ?
        ORDER BY week_start DESC LIMIT 1
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_weekly_plan_by_date(date_str: str, user_id: int = 1) -> dict | None:
    """특정 날짜가 속한 주간 계획 반환"""
    from datetime import datetime, timedelta
    d = datetime.fromisoformat(date_str[:10])
    monday = d - timedelta(days=d.weekday())
    week_start = monday.strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM weekly_plans WHERE user_id = ? AND week_start = ?",
        (user_id, week_start)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def save_weekly_plan(user_id: int, week_start: str, plan_json: str,
                     total_planned_km: float, phase: str, acwr: float,
                     notion_page_id: str = None) -> int:
    """주간 계획 저장 (같은 week_start면 업데이트)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO weekly_plans (
            user_id, week_start, plan_json, total_planned_km, phase, acwr, notion_page_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(week_start) DO UPDATE SET
            plan_json = excluded.plan_json,
            total_planned_km = excluded.total_planned_km,
            phase = excluded.phase,
            acwr = excluded.acwr,
            generated_at = datetime('now')
    """, (user_id, week_start, plan_json, total_planned_km, phase, acwr, notion_page_id))
    conn.commit()
    plan_id = cursor.lastrowid
    conn.close()
    return plan_id


def update_weekly_adherence(week_start: str, adherence_rate: float, user_id: int = 1):
    """주 종료 후 이행도 업데이트"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE weekly_plans SET adherence_rate = ? WHERE user_id = ? AND week_start = ?",
        (adherence_rate, user_id, week_start)
    )
    conn.commit()
    conn.close()


# ── ACWR 계산 ─────────────────────────────────────────────────────────────────

def calculate_acwr(user_id: int = 1) -> dict:
    """
    ACWR (Acute:Chronic Workload Ratio) 계산
    - Acute load: 최근 7일 총 거리
    - Chronic load: 최근 28일 평균 주간 거리
    - 안전 범위: 0.8~1.3
    """
    from datetime import datetime, timedelta
    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now()
    d7 = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    d28 = (now - timedelta(days=28)).strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT COALESCE(SUM(distance_km), 0) FROM activities WHERE user_id = ? AND date >= ?",
        (user_id, d7)
    )
    acute_km = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COALESCE(SUM(distance_km), 0) FROM activities WHERE user_id = ? AND date >= ?",
        (user_id, d28)
    )
    chronic_total = cursor.fetchone()[0]
    chronic_weekly = chronic_total / 4

    conn.close()

    acwr = round(acute_km / chronic_weekly, 2) if chronic_weekly > 0 else 1.0
    return {
        "acwr": acwr,
        "acute_km": round(acute_km, 1),
        "chronic_weekly_km": round(chronic_weekly, 1),
        "risk": "위험" if acwr > 1.5 else ("주의" if acwr > 1.3 else "안전"),
    }


# ── Monthly Reports ──────────────────────────────────────────────────────────

def save_monthly_report(user_id: int, year_month: str, total_km: float,
                        total_sessions: int, adherence_rate: float,
                        zone_distribution: str, fitness_assessment: str,
                        goal_progress: str, next_month_focus: str = "",
                        notion_page_id: str = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO monthly_reports (
            user_id, year_month, total_km, total_sessions, adherence_rate,
            zone_distribution, fitness_assessment, goal_progress, next_month_focus, notion_page_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(year_month) DO UPDATE SET
            total_km = excluded.total_km,
            total_sessions = excluded.total_sessions,
            adherence_rate = excluded.adherence_rate,
            zone_distribution = excluded.zone_distribution,
            fitness_assessment = excluded.fitness_assessment,
            goal_progress = excluded.goal_progress,
            next_month_focus = excluded.next_month_focus,
            generated_at = datetime('now')
    """, (user_id, year_month, total_km, total_sessions, adherence_rate,
          zone_distribution, fitness_assessment, goal_progress, next_month_focus, notion_page_id))
    conn.commit()
    report_id = cursor.lastrowid
    conn.close()
    return report_id


def get_monthly_activities(year_month: str, user_id: int = 1) -> list[dict]:
    """특정 월의 운동 목록 반환 (YYYY-MM)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, distance_km, avg_heartrate, avg_pace_sec, avg_cadence, elevation_gain
        FROM activities
        WHERE user_id = ? AND date LIKE ? AND distance_km > 0
        ORDER BY date ASC
    """, (user_id, f"{year_month}%"))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]



def is_already_processed(strava_id: int) -> bool:
    """이미 처리된 활동인지 확인 (중복 처리 방지)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM activities WHERE strava_id = ?",
        (strava_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None