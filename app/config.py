from dotenv import load_dotenv
import os

# .env 파일에서 환경 변수 로드
load_dotenv()

# 환경변수에서 값 꺼내기
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_WEBHOOK_VERIFY_TOKEN = os.getenv("STRAVA_WEBHOOK_VERIFY_TOKEN")

STRAVA_ACCESS_TOKEN = os.getenv("STRAVA_ACCESS_TOKEN")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")
STRAVA_ATHLETE_ID = os.getenv("STRAVA_ATHLETE_ID")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
# 러닝 위치 (서울 동작구 기준, 나중에 Strava GPS로 자동화)
WEATHER_NX = os.getenv("WEATHER_NX", "59")
WEATHER_NY = os.getenv("WEATHER_NY", "124")

NOTION_API_KEY = os.getenv("NOTION_API_KEY")

# Notion 데이터베이스 ID (Phase 1 코칭 시스템)
NOTION_GOALS_DB_ID = os.getenv("NOTION_GOALS_DB_ID")           # 목표 설정 DB
NOTION_PROFILE_DB_ID = os.getenv("NOTION_PROFILE_DB_ID")       # 체중/신체 정보 DB
NOTION_TRAINING_LOG_DB_ID = os.getenv("NOTION_TRAINING_LOG_DB_ID")  # 훈련 일지 DB
NOTION_WEEKLY_PLAN_DB_ID = os.getenv("NOTION_WEEKLY_PLAN_DB_ID")    # 주간 계획 DB
NOTION_MONTHLY_REPORT_DB_ID = os.getenv("NOTION_MONTHLY_REPORT_DB_ID")  # 월간 리포트 DB

# 필수 값 없으면 서버 시작 시 바로 에러
# Notion 코칭 DB는 선택값 (없으면 Notion 연동 스킵)
NOTION_COACHING_ENABLED = all([
    NOTION_GOALS_DB_ID,
    NOTION_TRAINING_LOG_DB_ID,
    NOTION_WEEKLY_PLAN_DB_ID,
])

required = {
    "STRAVA_CLIENT_ID": STRAVA_CLIENT_ID,
    "STRAVA_CLIENT_SECRET": STRAVA_CLIENT_SECRET,
    "STRAVA_WEBHOOK_VERIFY_TOKEN": STRAVA_WEBHOOK_VERIFY_TOKEN,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "CLAUDE_API_KEY": CLAUDE_API_KEY,
    "STRAVA_ACCESS_TOKEN": STRAVA_ACCESS_TOKEN,
    "STRAVA_REFRESH_TOKEN": STRAVA_REFRESH_TOKEN,
    "STRAVA_ATHLETE_ID": STRAVA_ATHLETE_ID,
    "WEATHER_API_KEY": WEATHER_API_KEY,
    "NOTION_API_KEY": NOTION_API_KEY,
}

for key, value in required.items():
    if not value:
        raise ValueError(f"환경변수 {key} 가 .env 파일에 설정되어 있지 않습니다.")