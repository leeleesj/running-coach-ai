import asyncio
import httpx
import app.config as config
from typing import TYPE_CHECKING

from app.core.logger import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from app.models.activity import ActivityData


async def send_message(text: str, retries: int = 3) -> bool:
    """
    텔레그램으로 메시지 전송 (ConnectTimeout 대비 재시도 포함)
    parse_mode="HTML" 로 설정하면 <b>굵게</b> 등 HTML 태그 사용 가능
    """
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": config.TELEGRAM_CHAT_ID,
                        "text": text,
                        "parse_mode": "HTML",
                    }
                )

            if response.status_code != 200:
                logger.error(f"텔레그램 전송 실패: {response.status_code} {response.text}")
                return False

            logger.info("텔레그램 전송 성공!")
            return True

        except httpx.TimeoutException as e:
            logger.warning(f"텔레그램 전송 타임아웃 (시도 {attempt}/{retries}): {e}")
            if attempt < retries:
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"텔레그램 전송 에러: {e}")
            return False

    logger.error("텔레그램 전송 최종 실패 (재시도 소진)")
    return False


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


def _format_rag_comparison(comparison: list) -> str:
    """
    RAG 구조화 데이터 → telegram 표시용 텍스트
    LLM 요약 없이 수치를 직접 표시
    """
    if not comparison:
        return ""

    lines = []
    for item in comparison:
        changes = []

        pace_diff = item.get("pace_diff", 0)
        if abs(pace_diff) >= 3:
            changes.append(f"페이스 {abs(int(pace_diff))}초 {'향상' if pace_diff > 0 else '저하'}")
        else:
            changes.append("페이스 유사")

        hr_diff = item.get("hr_diff", 0)
        if abs(hr_diff) >= 2:
            changes.append(f"심박 {abs(int(hr_diff))}bpm {'안정' if hr_diff > 0 else '상승'}")
        else:
            changes.append("심박 유사")

        dist_diff = item.get("dist_diff", 0)
        if abs(dist_diff) >= 0.5:
            changes.append(f"거리 {abs(round(dist_diff, 1))}km {'증가' if dist_diff > 0 else '감소'}")

        pace_sec = item.get("avg_pace_sec", 0)
        pace_str = f"{int(pace_sec // 60)}:{int(pace_sec % 60):02d}/km" if pace_sec else "N/A"

        lines.append(
            f"• {item['period']} ({item['date']}) "
            f"{item['distance_km']}km · {item['avg_heartrate']}bpm · {pace_str}\n"
            f"  → {', '.join(changes)}"
        )

    return "\n".join(lines)


def format_analysis_message(
    analysis: dict,
    rag_comparison: list = None,
    planned_session: dict = None,
    tomorrow_session: dict = None,
) -> str:
    """
    AI 분석 메시지 (두 번째 메시지)
    analysis: LLM JSON 응답
    rag_comparison: personal_rag.get_comparison_data() 결과
    planned_session: 오늘 계획 세션 (plan vs actual 표시용)
    tomorrow_session: 내일 계획 세션 (주간 계획 DB에서)
    """
    # RAG 비교 섹션
    rag_text = _format_rag_comparison(rag_comparison or [])
    rag_section = f"\n\n📊 <b>성장 기록</b>\n{rag_text}" if rag_text else ""

    # 계획 vs 실제 섹션
    plan_vs_actual = analysis.get("plan_vs_actual")
    plan_section = ""
    if planned_session and planned_session.get("type", "휴식") != "휴식":
        plan_section = f"\n\n📋 <b>계획 vs 실제</b>\n{plan_vs_actual or '-'}"

    # 내일 훈련 섹션 (주간 계획 DB 기반)
    tomorrow_section = ""
    if tomorrow_session:
        t_type = tomorrow_session.get("type", "휴식")
        if t_type == "휴식" or tomorrow_session.get("distance_km", 0) == 0:
            tomorrow_section = "\n\n🏃 <b>내일 계획</b>\n• 휴식"
        else:
            tomorrow_section = (
                f"\n\n🏃 <b>내일 계획</b>\n"
                f"• 종류: {t_type}\n"
                f"• 거리: {tomorrow_session.get('distance_km', '-')}km\n"
                f"• 페이스: {tomorrow_session.get('pace', '-')}\n"
                f"• 심박: {tomorrow_session.get('heartrate', '-')}bpm"
            )

    # 성장 기록 (progress)
    progress = analysis.get("progress")
    progress_section = f"\n\n📈 <b>성장 기록</b>\n{progress}" if progress else ""

    message = f"""🤖 <b>AI 코치 분석</b>

📝 <b>총평</b>
{analysis.get('summary', '')}

💓 <b>심박수 분석</b>
{analysis.get('heartrate_analysis', '')}

⚡ <b>페이스 패턴</b>
{analysis.get('pace_analysis', '')}{plan_section}{rag_section}{progress_section}{tomorrow_section}"""

    return message.strip()