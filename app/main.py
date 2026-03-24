import hmac
import httpx
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import RedirectResponse

import app.config as config
from app.ai.claude import analyze_activity, generate_weekly_schedule
from app.services.weather import get_weather, calculate_heartrate_correction
from app.services.strava import get_activity, get_weekly_activities, parse_activity
from app.models.database import init_db, save_activity, save_user
from app.services.telegram import send_message, format_activity_message
from app.services.notion import create_weekly_report, generate_weekly_analysis
from app.services.strava import get_weekly_activities

app = FastAPI(title="Running Coach AI")

@app.on_event("startup")
async def startup():
    init_db()


@app.get("/health")
async def health():
    # 서버가 살아있는지 확인하는 엔드포인트
    # CloudFlare Tunnel 연결 테스트할 때 씀
    return {"status": "ok", "service": "running-coach-ai"}


@app.get("/strava/login")
async def strava_login():
    # Strava 로그인 페이지로 리다이렉트
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={config.STRAVA_CLIENT_ID}"
        f"&redirect_uri=https://legendary-treatment-keyword-amd.trycloudflare.com/strava/callback"
        f"&response_type=code"
        f"&scope=activity:read_all"
    )
    return RedirectResponse(auth_url)


@app.get("/strava/callback")
async def strava_callback(code: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": config.STRAVA_CLIENT_ID,
                "client_secret": config.STRAVA_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
            }
        )
    token_data = response.json()

    # 유저 DB 저장 ← 추가
    save_user(
        athlete_id=token_data["athlete"]["id"],
        name=token_data["athlete"]["firstname"],
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],  # Unix timestamp
    )

    return {"message": "인증 완료!", "athlete": token_data["athlete"]["firstname"]}


@app.get("/webhook/strava")
async def verify_strava_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    # Strava가 Webhook 등록할 때 이 엔드포인트로 검증 요청을 보냄
    # verify_token이 맞으면 challenge 값을 그대로 돌려줘야 등록 완료됨
    if not hmac.compare_digest(
        hub_verify_token,
        config.STRAVA_WEBHOOK_VERIFY_TOKEN,
    ):
        raise HTTPException(status_code=403, detail="Invalid verify token")
    
    return {"hub.challenge": hub_challenge}


@app.post("/webhook/strava")
async def receive_strava_event(request: Request):
    data = await request.json()

    object_type = data.get("object_type")
    aspect_type = data.get("aspect_type")
    activity_id = data.get("object_id")
    athlete_id = data.get("owner_id")

    print(f"Webhook 수신: {object_type} {aspect_type} id={activity_id}")

    if object_type == "activity" and aspect_type in ("update", "create"):
        print(f"새 운동 감지! ID: {activity_id}")

        # 1. Strava API로 운동 상세 데이터 가져오기
        raw = await get_activity(activity_id, athlete_id)
        activity = parse_activity(raw)

        # 운동 시작 위치로 날씨 가져오기
        start_latlng = raw.get("start_latlng", [])
        if start_latlng:
            weather = await get_weather(
                lat=start_latlng[0], 
                lon=start_latlng[1]
            )
        else:
            weather = await get_weather()  # 기본 위치

        # 심박수 보정 계산
        hr_correction = calculate_heartrate_correction(weather)

        # 실제 심박수에 보정 적용
        if activity.get("avg_heartrate") and hr_correction["correction"]:
            adjusted_hr = round(activity["avg_heartrate"] - hr_correction["correction"], 1)
            hr_correction["adjusted_heartrate"] = adjusted_hr
            print(f"심박 보정: {activity['avg_heartrate']}bpm → {adjusted_hr}bpm ({hr_correction['comment']})")

        # 2. 이번 주 활동 가져오기
        weekly = await get_weekly_activities(athlete_id)

        # 3. DB에 저장
        save_activity(activity)

        # 4. Claude 분석
        analysis = await analyze_activity(activity, weekly, weather, hr_correction)

        # 차주 훈련 스케줄 생성
        schedule = await generate_weekly_schedule(activity, weekly, weather, hr_correction)

        # 5. Telegram 메시지로 전송 (기존 요약 + Claude 분석 합쳐서)
        message = format_activity_message(activity, weather)
        message += f"\n\n🤖 <b>AI 코치 분석</b>\n{analysis}"
        message += f"\n\n📅 <b>다음 주 훈련 스케줄</b>\n{schedule}"
        await send_message(message)

        print(f"=== 운동 분석 결과 ===")
        print(f"날짜: {activity['date']}")
        print(f"거리: {activity['distance_km']} km")
        print(f"시간: {activity['moving_time']}")
        print(f"평균 페이스: {activity['pace']}")
        print(f"최고 페이스: {activity['max_pace']}")
        print(f"평균 심박: {activity['avg_heartrate']} bpm")
        print(f"최고 심박: {activity['max_heartrate']} bpm")
        print(f"케이던스: {activity['avg_cadence']} spm")
        print(f"칼로리: {activity['calories']} kcal")
        print(f"고도 상승: {activity['elevation_gain']} m")
        if activity['pr_rank'] == 1:
            print(f"🏆 역대 최고 페이스!")
        elif activity['pr_rank']:
            print(f"기록 순위: {activity['pr_rank']}위")

        print(f"\n--- km별 구간 분석 ---")
        for s in activity['splits']:
            print(f"{s['km']}km: 페이스 {s['pace']} | 심박 {s['avg_heartrate']} bpm")
        print(f"====================")

    return {"status": "EVENT_RECEIVED"}


@app.get("/test/weather")
async def test_weather():
    from app.services.weather import get_weather
    weather = await get_weather()
    return weather


@app.get("/test/notion")
async def test_notion():
    weekly = await get_weekly_activities(196195036)
    analysis = await generate_weekly_analysis(weekly)

    from app.ai.claude import generate_weekly_schedule
    # 빈 activity 대신 기본값 딕셔너리 전달
    empty_activity = {
        "distance_km": 0,
        "pace": "N/A",
        "avg_heartrate": 0,
        "splits": [],
        "moving_time": "0:00",
        "max_pace": "N/A",
        "max_heartrate": 0,
        "avg_cadence": 0,
        "calories": 0,
        "elevation_gain": 0,
        "pr_rank": None,
        "name": "주간 스케줄 생성",
        "date": "",
    }
    schedule = await generate_weekly_schedule(empty_activity, weekly)
    result = await create_weekly_report(weekly, analysis, schedule)
    return {"success": result, "analysis": analysis}