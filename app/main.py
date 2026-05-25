import hmac
import httpx
import asyncio
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse

import app.config as config
from app.core.logger import get_logger

logger = get_logger(__name__)
from app.ai.local_llm import analyze_activity, parse_llm_response
from app.services.weather import get_weather, calculate_heartrate_correction
from app.services.strava import get_activity, get_weekly_activities, parse_activity
from app.models.database import init_db, save_activity, save_splits, save_user, is_already_processed
from app.services.telegram import send_message, format_activity_message, format_analysis_message
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 라이프사이클 관리"""
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Running Coach AI", lifespan=lifespan)

# 처리 중인 activity_id 추적 (중복 방지)
processing_ids: set = set()


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

    logger.info(f"Webhook 수신: {object_type} {aspect_type} id={activity_id}")

    if object_type == "activity" and aspect_type in ("create", "update"):
        # 현재 처리 중인 activity면 스킵
        if activity_id in processing_ids:
            logger.info(f"이미 처리 중, 스킵: {activity_id}")
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
            logger.info(f"이미 처리된 활동, 스킵: {activity_id}")
            return

        logger.info(f"새 운동 처리 시작! ID: {activity_id}")

        # 1. Strava 데이터 가져오기
        # create 직후엔 Strava가 GPS 처리 중 → splits_metric 비어있을 수 있음
        if aspect_type == "create":
            logger.info("create 이벤트: 30초 대기 (Strava GPS 처리 완료 후 fetch)")
            await asyncio.sleep(30)
        raw = await get_activity(activity_id, athlete_id)
        if not raw:
            logger.warning(f"운동 데이터 가져오기 실패: {activity_id}")
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
            logger.warning(f"날씨 API 실패 (계속 진행): {e}")

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
                    logger.info(f"심박 보정: {activity.avg_heartrate}bpm → {adjusted_hr}bpm ({hr_correction['comment']})")
        except Exception as e:
            logger.warning(f"심박 보정 실패 (계속 진행): {e}")

        # 4. 이번 주 활동 가져오기
        weekly = []
        try:
            weekly = await get_weekly_activities(athlete_id)
        except Exception as e:
            logger.warning(f"주간 활동 가져오기 실패 (계속 진행): {e}")

        # 5. DB 저장
        activity_db_id = 0
        try:
            activity_db_id = save_activity(activity)
            save_splits(activity_db_id, activity.splits)
        except Exception as e:
            logger.error(f"DB 저장 실패 (계속 진행): {e}")
            await send_message(f"⚠️ DB 저장 실패: {str(e)}")

        # 5-1. Personal RAG 인덱스 업데이트 + 비교 데이터 수집
        rag_comparison = []
        try:
            from app.rag.personal_rag import get_personal_rag
            rag = get_personal_rag()
            if rag.collection.count() > 0:
                activity_dict = {
                    "id": activity_db_id,
                    "date": activity.date,
                    "distance_km": activity.distance_km,
                    "avg_pace_sec": activity.avg_pace_sec,
                    "avg_heartrate": activity.avg_heartrate,
                    "max_heartrate": activity.max_heartrate,
                    "avg_cadence": activity.avg_cadence,
                    "elevation_gain": activity.elevation_gain,
                    "calories": activity.calories,
                }
                rag_comparison = rag.get_comparison_data(activity_dict)
                rag.upsert_activity(activity_dict)
                logger.info(f"Personal RAG 인덱스 업데이트 완료 (유사 운동 {len(rag_comparison)}개)")
        except Exception as e:
            logger.warning(f"Personal RAG 업데이트 실패 (무시하고 계속): {e}")

        # 5-2. 오늘 계획 세션 + 내일 계획 세션 조회 (주간 계획 DB)
        planned_session = None
        tomorrow_session = None
        try:
            from app.models.database import get_current_weekly_plan
            from app.coaches.weekly_coach import get_today_planned_session, get_tomorrow_planned_session
            import json
            weekly_plan_row = get_current_weekly_plan()
            if weekly_plan_row and weekly_plan_row.get("plan_json"):
                weekly_plan = json.loads(weekly_plan_row["plan_json"])
                planned_session = get_today_planned_session(weekly_plan)
                tomorrow_session = get_tomorrow_planned_session(weekly_plan)
                logger.info(f"주간 계획 조회 완료: 오늘={planned_session and planned_session.get('type')}, 내일={tomorrow_session and tomorrow_session.get('type')}")
        except Exception as e:
            logger.warning(f"주간 계획 조회 실패 (무시하고 계속): {e}")

        # 6. 첫 번째 메시지: 운동 요약 즉시 전송
        try:
            summary_message = format_activity_message(activity, weather)
            await send_message(summary_message)
        except Exception as e:
            logger.error(f"운동 요약 전송 실패: {e}")

        # 7. LLM 분석
        analysis_text = ""
        analysis_dict = None
        try:
            analysis_text = await analyze_activity(
                activity, weekly, weather, hr_correction,
                activity_db_id=activity_db_id,
                planned_session=planned_session,
            )
            analysis_dict = parse_llm_response(analysis_text)
        except Exception as e:
            logger.error(f"LLM 분석 실패: {e}")

        # 7-1. Notion 훈련 일지 기록 (분석 완료 후)
        ai_comment = ""
        if analysis_dict:
            ai_comment = analysis_dict.get("summary", "")
        try:
            from app.services.notion import post_training_log
            await post_training_log(
                activity={
                    "date": activity.date,
                    "name": activity.name,
                    "strava_id": activity.id,
                    "distance_km": activity.distance_km,
                    "avg_heartrate": activity.avg_heartrate,
                    "max_heartrate": activity.max_heartrate,
                    "avg_pace_sec": activity.avg_pace_sec,
                    "avg_cadence": activity.avg_cadence,
                    "elevation_gain": activity.elevation_gain,
                    "calories": activity.calories,
                    "training_type": activity.training_type,
                },
                planned_session=planned_session,
                ai_comment=ai_comment,
            )
        except Exception as e:
            logger.warning(f"Notion 훈련 일지 기록 실패 (무시하고 계속): {e}")

        # 8. 두 번째 메시지: AI 분석 전송
        try:
            if analysis_dict:
                analysis_message = format_analysis_message(
                    analysis_dict,
                    rag_comparison=rag_comparison,
                    planned_session=planned_session,
                    tomorrow_session=tomorrow_session,
                )
            else:
                # JSON 파싱 실패 시 텍스트 그대로
                logger.warning("JSON 파싱 실패, 텍스트로 전송")
                analysis_message = f"🤖 <b>AI 코치 분석</b>\n{analysis_text}"
            await send_message(analysis_message)
        except Exception as e:
            logger.error(f"AI 분석 전송 실패: {e}")
            traceback.print_exc()

        # 터미널 출력
        logger.info("=== 운동 분석 완료 ===")
        logger.info(f"날짜: {activity.date}")
        logger.info(f"거리: {activity.distance_km} km")
        logger.info(f"페이스: {activity.pace}")
        logger.info(f"심박: {activity.avg_heartrate} bpm")
        if activity.pr_rank == 1:
            logger.info("역대 최고 페이스!")
        elif activity.pr_rank:
            logger.info(f"기록 순위: {activity.pr_rank}위")
        logger.info("====================")

    except Exception as e:
        logger.error(f"예상치 못한 에러: {activity_id}, {e}")
        try:
            await send_message(f"⚠️ 예상치 못한 오류가 발생했어요.\n{str(e)}")
        except:
            pass

    finally:
        await asyncio.sleep(60)
        processing_ids.discard(activity_id)


# ── 테스트 엔드포인트 ──────────────────────────

@app.get("/test/weather")
async def test_weather():
    weather = await get_weather()
    return weather


@app.get("/test/weekly-coach")
async def test_weekly_coach():
    """주간 코치 수동 실행 (테스트용)"""
    from app.coaches.weekly_coach import generate_weekly_plan, format_weekly_plan_message
    plan = await generate_weekly_plan(user_id=1)
    if not plan:
        return {"error": "주간 계획 생성 실패"}
    msg = format_weekly_plan_message(plan)
    return {"plan": plan, "message": msg}


@app.get("/test/monthly-coach")
async def test_monthly_coach(year_month: str = None):
    """월간 코치 수동 실행 (테스트용, year_month: YYYY-MM)"""
    from app.coaches.monthly_coach import generate_monthly_report, format_monthly_report_message
    report = await generate_monthly_report(user_id=1, year_month=year_month)
    if not report:
        return {"error": "월간 리포트 생성 실패"}
    msg = format_monthly_report_message(report)
    return {"report": report, "message": msg}
