"""주간 코치 테스트 스크립트"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.coaches.weekly_coach import generate_weekly_plan, format_weekly_plan_message


async def test():
    plan = await generate_weekly_plan(user_id=1)
    if plan:
        print(format_weekly_plan_message(plan))
    else:
        print("생성 실패")


asyncio.run(test())
