"""월간 코치 테스트 스크립트"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.coaches.monthly_coach import generate_monthly_report, format_monthly_report_message


async def test():
    report = await generate_monthly_report(user_id=1, year_month="2026-04")
    if report:
        print(format_monthly_report_message(report))
    else:
        print("생성 실패")


asyncio.run(test())
