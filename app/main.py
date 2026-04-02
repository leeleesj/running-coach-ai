import hmac
import httpx
import asyncio
from fastapi import FastAPI, Request, Query, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse

import app.config as config
from app.ai.local_llm import analyze_activity, generate_weekly_schedule, parse_llm_response
from app.services.weather import get_weather, calculate_heartrate_correction
from app.services.strava import get_activity, get_weekly_activities, parse_activity
from app.models.database import init_db, save_activity, save_splits, save_user, is_already_processed
from app.services.telegram import send_message, format_activity_message, format_analysis_message
from app.services.notion import create_weekly_report, generate_weekly_analysis

app = FastAPI(title="Running Coach AI")

# 처리 중인 activity_id 추적 (중복 방지)
processing_ids: set = set()


@app.on_event("startup")
async def startup():
    init_db()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "running-coach-ai"}


@app.get("/strava/login")
async def strava_login():
    auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={config.STRAVA_CLIENT_ID}"
        f"&redirect_uri=https://newport-technology-appreciation-karl.trycloudflare.com/strava/callback"
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

    save_user(
        athlete_id=token_data["athlete"]["id"],
        name=token_data["athlete"]["firstname"],
        access_token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        expires_at=token_data["expires_at"],
    )

    return {"message": "인증 완료!", "athlete": token_data["athlete"]["firstname"]}


@app.get("/webhook/strava")
async def verify_strava_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_challenge: str = Query(alias="hub.challenge"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
):
    if not hmac.compare_digest(
        hub_verify_token,
        config.STRAVA_WEBHOOK_VERIFY_TOKEN,
    ):
        raise HTTPException(status_code=403, detail="Invalid verify token")

    return {"hub.challenge": hub_challenge}


@app.post("/webhook/strava")
async def receive_strava_event(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    object_type = data.get("object_type")
    aspect_type = data.get("aspect_type")
    activity_id = data.get("object_id")
    athlete_id = data.get("owner_id")

    print(f"Webhook 수신: {object_type} {aspect_type} id={activity_id}")

    if object_type == "activity" and aspect_type in ("create", "update"):
        # 현재 처리 중인 activity면 스킵
        if activity_id in processing_ids:
            print(f"이미 처리 중, 스킵: {activity_id}")
            return {"status": "EVENT_RECEIVED"}

        # 백그라운드로 처리 (즉시 200 반환)
        background_tasks.add_task(
            process_activity,
            activity_id,
            athlete_id,
            aspect_type,
        )

    return {"status": "EVENT_RECEIVED"}


async def process_activity(activity_id: int, athlete_id: int, aspect_type: str):
    """백그라운드에서 운동 데이터 처리"""

    processing_ids.add(activity_id)

    try:
        # create 이벤트 중복 방지
        if aspect_type == "create" and is_already_processed(activity_id):
            print(f"이미 처리된 활동, 스킵: {activity_id}")
            return

        print(f"새 운동 처리 시작! ID: {activity_id}")

        # 1. Strava 데이터 가져오기
        raw = await get_activity(activity_id, athlete_id)
        if not raw:
            print(f"운동 데이터 가져오기 실패: {activity_id}")
            await send_message(f"⚠️ 운동 데이터를 가져오지 못했어요. (ID: {activity_id})")
            return

        activity = parse_activity(raw)

        # 2. 날씨 가져오기 (실패해도 계속)
        weather = {}
        try:
            start_latlng = raw.get("start_latlng", [])
            if start_latlng:
                weather = await get_weather(lat=start_latlng[0], lon=start_latlng[1])
            else:
                weather = await get_weather()
        except Exception as e:
            print(f"날씨 API 실패 (계속 진행): {e}")

        # 3. 심박 보정 (날씨 없으면 스킵)
        hr_correction = {}
        try:
            if weather:
                hr_correction = calculate_heartrate_correction(weather)
                if activity.avg_heartrate and hr_correction.get("correction"):
                    adjusted_hr = round(activity.avg_heartrate - hr_correction["correction"], 1)
                    hr_correction["adjusted_heartrate"] = adjusted_hr
                    activity.avg_heartrate_adjusted = adjusted_hr
                    activity.hr_correction = hr_correction["correction"]
                    activity.hr_correction_comment = hr_correction["comment"]
                    print(f"심박 보정: {activity.avg_heartrate}bpm → {adjusted_hr}bpm ({hr_correction['comment']})")
        except Exception as e:
            print(f"심박 보정 실패 (계속 진행): {e}")

        # 4. 이번 주 활동 가져오기
        weekly = []
        try:
            weekly = await get_weekly_activities(athlete_id)
        except Exception as e:
            print(f"주간 활동 가져오기 실패 (계속 진행): {e}")

        # 5. DB 저장
        try:
            activity_db_id = save_activity(activity)
            save_splits(activity_db_id, activity.splits)
        except Exception as e:
            print(f"DB 저장 실패 (계속 진행): {e}")
            await send_message(f"⚠️ DB 저장 실패: {str(e)}")

        # 6. 첫 번째 메시지: 운동 요약 즉시 전송
        try:
            summary_message = format_activity_message(activity, weather)
            await send_message(summary_message)
        except Exception as e:
            print(f"운동 요약 전송 실패: {e}")

        # 7. LLM 분석
        analysis_text = ""
        analysis_dict = None
        schedule = ""
        try:
            analysis_text = await analyze_activity(activity, weekly, weather, hr_correction)
            analysis_dict = parse_llm_response(analysis_text)
            schedule = await generate_weekly_schedule(activity, weekly, weather, hr_correction)
        except Exception as e:
            print(f"LLM 분석 실패: {e}")

        # 8. 두 번째 메시지: AI 분석 전송
        try:
            if analysis_dict:
                analysis_message = format_analysis_message(analysis_dict, schedule)
            else:
                # JSON 파싱 실패 시 텍스트 그대로
                print("JSON 파싱 실패, 텍스트로 전송")
                analysis_message = f"🤖 <b>AI 코치 분석</b>\n{analysis_text}"
                if schedule:
                    analysis_message += f"\n\n📅 <b>다음 주 스케줄</b>\n{schedule}"
            await send_message(analysis_message)
        except Exception as e:
            print(f"AI 분석 전송 실패: {e}")

        # 터미널 출력
        print(f"=== 운동 분석 완료 ===")
        print(f"날짜: {activity.date}")
        print(f"거리: {activity.distance_km} km")
        print(f"페이스: {activity.pace}")
        print(f"심박: {activity.avg_heartrate} bpm")
        if activity.pr_rank == 1:
            print(f"🏆 역대 최고 페이스!")
        elif activity.pr_rank:
            print(f"기록 순위: {activity.pr_rank}위")
        print(f"====================")

    except Exception as e:
        print(f"예상치 못한 에러: {activity_id}, {e}")
        try:
            await send_message(f"⚠️ 예상치 못한 오류가 발생했어요.\n{str(e)}")
        except:
            pass

    finally:
        await asyncio.sleep(300)
        processing_ids.discard(activity_id)


# ── 테스트 엔드포인트 ──────────────────────────

@app.get("/test/weather")
async def test_weather():
    weather = await get_weather()
    return weather


@app.get("/test/notion")
async def test_notion():
    weekly = await get_weekly_activities(196195036)
    analysis = await generate_weekly_analysis(weekly)

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