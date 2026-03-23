import sqlite3
import json
from pathlib import Path
from datetime import datetime

# DB 파일 경로
DB_PATH = Path("data/running_coach.db")


def get_connection():
    """DB 연결 반환. Row를 딕셔너리로 접근 가능하게 설정"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # result["column_name"] 으로 접근 가능
    return conn


def init_db():
    """테이블 생성. 서버 시작 시 한 번 실행"""
    DB_PATH.parent.mkdir(exist_ok=True)  # data/ 폴더 없으면 생성

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
            name TEXT,
            type TEXT DEFAULT 'Run',
            date TEXT,
            distance_km REAL,
            moving_time INTEGER,
            avg_pace_sec REAL,
            avg_heartrate REAL,
            max_heartrate REAL,
            avg_cadence INTEGER,
            calories REAL,
            elevation_gain REAL,
            splits_json TEXT,
            raw_json TEXT,
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

    conn.commit()
    conn.close()
    print("DB 초기화 완료!")


def save_activity(parsed: dict, user_id: int = 1) -> int:
    """
    파싱된 운동 데이터를 DB에 저장
    이미 저장된 strava_id면 업데이트, 없으면 새로 삽입 (upsert)
    """
    print(f"저장할 데이터: id={parsed.get('id')}, name={parsed.get('name')}")  # ← 추가

    conn = get_connection()
    cursor = conn.cursor()

    # 페이스를 초/km로 변환 (6:16 → 376초)
    avg_pace_sec = None
    if parsed.get("pace") and parsed["pace"] != "N/A":
        pace_parts = parsed["pace"].replace(" /km", "").split(":")
        avg_pace_sec = int(pace_parts[0]) * 60 + int(pace_parts[1])

    cursor.execute("""
        INSERT INTO activities (
            user_id, strava_id, name, type, date,
            distance_km, moving_time, avg_pace_sec,
            avg_heartrate, max_heartrate, avg_cadence,
            calories, elevation_gain, splits_json, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(strava_id) DO UPDATE SET
            name=excluded.name,
            avg_heartrate=excluded.avg_heartrate,
            max_heartrate=excluded.max_heartrate,
            calories=excluded.calories,
            splits_json=excluded.splits_json,
            raw_json=excluded.raw_json
    """, (
        user_id,
        parsed["id"],
        parsed["name"],
        parsed["type"],
        parsed["date"],
        parsed["distance_km"],
        parsed.get("moving_time_sec"),  # 초 단위
        avg_pace_sec,
        parsed["avg_heartrate"],
        parsed["max_heartrate"],
        parsed["avg_cadence"],
        parsed["calories"],
        parsed["elevation_gain"],
        json.dumps(parsed["splits"], ensure_ascii=False),
        json.dumps(parsed.get("raw", {}), ensure_ascii=False),
    ))

    conn.commit()
    activity_db_id = cursor.lastrowid
    conn.close()

    print(f"DB 저장 완료! db_id={activity_db_id}")
    return activity_db_id


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