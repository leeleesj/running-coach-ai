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

# 필수 값 없으면 서버 시작 시 바로 에러
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
}

for key, value in required.items():
    if not value:
        raise ValueError(f"환경변수 {key} 가 .env 파일에 설정되어 있지 않습니다.")