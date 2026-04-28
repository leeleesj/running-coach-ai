"""
APScheduler 기반 크론 스케줄러

등록된 작업:
  - 매주 월요일 07:00 → 주간 코치 (계획 생성 + Notion + 텔레그램)
  - 매월 1일 08:00  → 월간 코치 (리포트 + Notion + 텔레그램)
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

KST = pytz.timezone("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone=KST)


async def _run_weekly_coach():
    """매주 월요일 07:00 실행"""
    print("[스케줄러] 주간 코치 시작")
    try:
        from app.coaches.weekly_coach import generate_weekly_plan, format_weekly_plan_message
        from app.services.notion import post_weekly_plan
        from app.services.telegram import send_message

        plan = await generate_weekly_plan(user_id=1)
        if plan:
            # Notion 기록
            await post_weekly_plan(plan)
            # 텔레그램 발송
            msg = format_weekly_plan_message(plan)
            await send_message(msg)
            print("[스케줄러] 주간 코치 완료")
        else:
            print("[스케줄러] 주간 계획 생성 실패")
    except Exception as e:
        import traceback
        print(f"[스케줄러] 주간 코치 에러: {e}")
        traceback.print_exc()


async def _run_monthly_coach():
    """매월 1일 08:00 실행"""
    print("[스케줄러] 월간 코치 시작")
    try:
        from app.coaches.monthly_coach import generate_monthly_report, format_monthly_report_message
        from app.services.notion import post_monthly_report
        from app.services.telegram import send_message

        report = await generate_monthly_report(user_id=1)
        if report:
            # Notion 기록
            await post_monthly_report(report)
            # 텔레그램 발송
            msg = format_monthly_report_message(report)
            await send_message(msg)
            print("[스케줄러] 월간 코치 완료")
        else:
            print("[스케줄러] 월간 리포트 생성 실패")
    except Exception as e:
        import traceback
        print(f"[스케줄러] 월간 코치 에러: {e}")
        traceback.print_exc()


def start_scheduler():
    """FastAPI 시작 시 호출"""
    # 매주 월요일 07:00 (KST)
    scheduler.add_job(
        _run_weekly_coach,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=KST),
        id="weekly_coach",
        replace_existing=True,
    )
    # 매월 1일 08:00 (KST)
    scheduler.add_job(
        _run_monthly_coach,
        trigger=CronTrigger(day=1, hour=8, minute=0, timezone=KST),
        id="monthly_coach",
        replace_existing=True,
    )
    scheduler.start()
    print("스케줄러 시작: 주간 코치(월 07:00), 월간 코치(1일 08:00)")


def stop_scheduler():
    """FastAPI 종료 시 호출"""
    if scheduler.running:
        scheduler.shutdown()
        print("스케줄러 종료")
