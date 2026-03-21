import hmac
import httpx
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import RedirectResponse

import app.config as config
from app.services.strava import get_activity, get_weekly_activities, parse_activity
from app.models.database import init_db, save_activity
from app.services.telegram import send_message, format_activity_message

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
    # Strava가 code를 가지고 콜백으로 돌아옴
    # code → access_token 교환
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
    print(f"Access Token: {token_data.get('access_token')}")
    print(f"Refresh Token: {token_data.get('refresh_token')}")
    print(f"Athlete ID: {token_data.get('athlete', {}).get('id')}")

    return {"message": "인증 완료!", "athlete": token_data.get('athlete', {}).get('firstname')}


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

    print(f"Webhook 수신: {object_type} {aspect_type} id={activity_id}")

    if object_type == "activity" and aspect_type in ("update", "create"):
        print(f"새 운동 감지! ID: {activity_id}")

        # 1. Strava API로 운동 상세 데이터 가져오기
        raw = await get_activity(activity_id)
        activity = parse_activity(raw)

        # 2. DB에 저장
        save_activity(activity)

        # 3. Telegram 메시지로 전송
        message = format_activity_message(activity)
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