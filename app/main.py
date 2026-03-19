from fastapi import FastAPI, Request, Query, HTTPException
import hmac
import app.config as config

app = FastAPI(title="Running Coach AI")

@app.get("/health")
async def health():
    # 서버가 살아있는지 확인하는 엔드포인트
    # CloudFlare Tunnel 연결 테스트할 때 씀
    return {"status": "ok", "service": "running-coach-ai"}

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
    # 운동 이벤트 수신
    # 러닝 끝나면 Strava가 여기로 POST 요청 보냄
    data = await request.json()

    object_type = data.get("object_type")   # "activity" 또는 "athlete"
    aspect_type = data.get("aspect_type")   # "create", "update", "delete" 중 하나   
    activity_id = data.get("object_id")

    print(f"Webhook 수신: {object_type} {aspect_type} id={activity_id}")

    # 운동 생성 이벤트만 처리 (수정/삭제 무시)
    if object_type == "activity" and aspect_type == "create":
        print(f"새 운동 감지! ID: {activity_id}")
        # 다음 단계에서 여기에 AI 코치 로직 추가할 예정 

    # Strava는 200 OK 안 오면 재시도함 - 반드시 200 반환
    return {"status": "EVENT_RECEIVED"}