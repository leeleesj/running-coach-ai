import sqlite3
import json
from pathlib import Path

# DB 파일 경로
DB_PATH = Path("data/running_coach.db")


def get_connection():
    """DB 연결 반환. Row를 딕셔너리로 접근 가능하게 설정"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # result["column_name"] 으로 접근 가능
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
            zone1_max INTEGER DEFAULT 115,
            zone2_max INTEGER DEFAULT 152,
            zone3_max INTEGER DEFAULT 171,
            zone4_max INTEGER DEFAULT 190,
            zone5_max INTEGER DEFAULT 220,
            max_heartrate INTEGER DEFAULT 220,
            resting_heartrate INTEGER DEFAULT 60,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            week_start TEXT,
            week_end TEXT,
            total_distance REAL,
            total_count INTEGER,
            avg_heartrate REAL,
            analysis_json TEXT,
            schedule_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            date TEXT,
            meal_type TEXT,
            description TEXT,
            calories REAL,
            protein REAL,
            carbs REAL,
            fat REAL,
            photo_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # 기존 테이블에 새 컬럼 추가 (마이그레이션)
    # 이미 있는 컬럼이면 에러 무시
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
            pass  # 이미 존재하는 컬럼이면 무시

    conn.commit()
    conn.close()
    print("DB 초기화 완료!")


def save_activity(parsed: dict, user_id: int = 1) -> int:
    """
    파싱된 운동 데이터를 DB에 저장
    이미 저장된 strava_id면 업데이트, 없으면 새로 삽입 (upsert)
    보정된 심박수는 main.py에서 parsed에 추가 후 넘겨줌
    """
    print(f"저장할 데이터: id={parsed.get('id')}, name={parsed.get('name')}")
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
        parsed["id"],
        parsed["name"],
        parsed["type"],
        parsed.get("workout_type"),
        parsed.get("device_name"),
        parsed["date"],
        parsed["distance_km"],
        parsed.get("moving_time_sec"),
        parsed.get("elapsed_time_sec"),
        parsed.get("avg_pace_sec"),
        parsed.get("max_pace_sec"),
        parsed.get("avg_heartrate"),
        parsed.get("max_heartrate"),
        parsed.get("avg_heartrate_adjusted"),
        parsed.get("hr_correction"),
        parsed.get("hr_correction_comment"),
        parsed.get("avg_cadence"),
        parsed.get("elevation_gain"),
        parsed.get("elev_high"),
        parsed.get("elev_low"),
        parsed.get("calories"),
        parsed.get("suffer_score"),
        parsed.get("perceived_exertion"),
        parsed.get("pr_count"),
        parsed.get("achievement_count"),
        parsed.get("pr_rank"),
        parsed.get("trend_direction"),
        json.dumps(parsed.get("splits", []), ensure_ascii=False),
        json.dumps(parsed.get("raw", {}), ensure_ascii=False),
    ))

    conn.commit()

    # 저장된 activity의 db_id 가져오기
    cursor.execute(
        "SELECT id FROM activities WHERE strava_id = ?",
        (parsed["id"],)
    )
    row = cursor.fetchone()
    activity_db_id = row["id"] if row else 0
    conn.close()

    print(f"DB 저장 완료! db_id={activity_db_id}")
    return activity_db_id


def save_splits(activity_db_id: int, splits: list) -> None:
    """
    km별 구간 데이터를 splits 테이블에 저장
    activity_db_id: activities 테이블의 id (strava_id 아님)
    """
    if not splits:
        return

    conn = get_connection()
    cursor = conn.cursor()

    # 기존 splits 삭제 후 재삽입
    cursor.execute("DELETE FROM splits WHERE activity_id = ?", (activity_db_id,))

    for split in splits:
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
    print(f"splits 저장 완료! {len(splits)}개 구간")


def save_user(athlete_id: int, name: str, access_token: str,
              refresh_token: str, expires_at: int) -> int:
    """
    유저 저장 또는 업데이트 (upsert)
    OAuth 완료할 때마다 호출
    """
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

    print(f"유저 저장 완료! athlete_id={athlete_id}")
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
    print(f"토큰 갱신 완료! expires_at={expires_at}")


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