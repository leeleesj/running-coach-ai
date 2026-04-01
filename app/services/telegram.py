import httpx
import app.config as config
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.activity import ActivityData


async def send_message(text: str) -> bool:
    """
    텔레그램으로 메시지 전송
    parse_mode="HTML" 로 설정하면 <b>굵게</b> 등 HTML 태그 사용 가능
    """
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
            }
        )

    if response.status_code != 200:
        print(f"텔레그램 전송 실패: {response.status_code} {response.text}")
        return False

    print("텔레그램 전송 성공!")
    return True


def format_activity_message(activity: "ActivityData", weather: dict = None) -> str:
    """
    운동 요약 메시지 (첫 번째 메시지)
    핵심 정보만 간결하게
    """
    # 심박수 존 판단 (나중에 Ollama로 대체 예정)
    avg_hr = activity.avg_heartrate or 0
    if avg_hr < 140:
        hr_comment = "✅ 존2 유지"
    elif avg_hr < 160:
        hr_comment = "⚠️ 존3"
    else:
        hr_comment = "🔥 고강도"

    # PR 여부
    pr_text = ""
    if activity.pr_rank == 1:
        pr_text = "\n🏆 역대 최고 페이스!"
    elif activity.pr_rank:
        pr_text = f"\n🥈 기록 순위 {activity.pr_rank}위"

    # 속도 트렌드
    trend_text = ""
    if activity.trend_direction == 1:
        trend_text = "\n📈 속도 트렌드 향상 중!"
    elif activity.trend_direction == -1:
        trend_text = "\n📉 속도 트렌드 저하 중"

    # 날씨 텍스트
    weather_text = ""
    if weather:
        weather_text = f"\n🌤 {weather['sky']} {weather['temperature']}°C | 습도 {weather['humidity']}% | 바람 {weather['wind_speed']}m/s"

    # 심박 보정 텍스트
    hr_adjusted_text = ""
    if activity.avg_heartrate_adjusted:
        hr_adjusted_text = f" → 보정 {activity.avg_heartrate_adjusted}bpm"

    # km별 구간 (간결하게)
    splits_text = ""
    for s in activity.splits:
        splits_text += f"  {s.km}km {s.pace} 💓{s.avg_heartrate}bpm\n"

    message = f"""🏃 <b>러닝 완료!</b>
📅 {activity.date_display}
📍 {activity.name}{weather_text}

<b>거리</b> {activity.distance_km}km  <b>시간</b> {activity.moving_time}
<b>페이스</b> {activity.pace}  <b>심박</b> {activity.avg_heartrate}bpm{hr_adjusted_text} {hr_comment}
<b>케이던스</b> {activity.avg_cadence}spm  <b>칼로리</b> {activity.calories}kcal{pr_text}{trend_text}

📈 <b>구간별</b>
{splits_text}"""

    return message.strip()


def format_analysis_message(analysis: dict, schedule: str) -> str:
    """
    AI 분석 메시지 (두 번째 메시지)
    Claude JSON 응답을 HTML로 포맷
    """
    tomorrow = analysis.get("tomorrow", {})

    message = f"""🤖 <b>AI 코치 분석</b>

📝 <b>총평</b>
{analysis.get('summary', '')}

💓 <b>심박수 분석</b>
{analysis.get('heartrate_analysis', '')}

📈 <b>페이스 패턴</b>
{analysis.get('pace_analysis', '')}

🏃 <b>내일 추천 훈련</b>
• 종류: {tomorrow.get('type', 'N/A')}
• 거리: {tomorrow.get('distance', 'N/A')}
• 페이스: {tomorrow.get('pace', 'N/A')}
• 심박: {tomorrow.get('heartrate', 'N/A')}

🎯 <b>하프마라톤 준비</b>
{analysis.get('marathon_status', '')}

📅 <b>다음 주 스케줄</b>
{schedule}"""

    return message.strip()