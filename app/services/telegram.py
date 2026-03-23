import httpx
import app.config as config


async def send_message(text: str) -> bool:
    """
    텔레그램으로 메시지 전송

    parse_mode="HTML" 로 설정하면 <b>굵게</b>, <i>기울임</i> 등 HTML 태그 사용 가능
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


def format_activity_message(activity: dict, weather: dict = None) -> str:
    """
    파싱된 운동 데이터를 텔레그램 메시지로 포맷

    HTML 태그로 보기 좋게 꾸밈
    """
    # 심박수 존 판단
    avg_hr = activity.get("avg_heartrate") or 0
    if avg_hr < 140:
        hr_comment = "✅ 존2 유지 잘됐어요!"
    elif avg_hr < 160:
        hr_comment = "⚠️ 존3 진입, 조금 힘들었죠?"
    else:
        hr_comment = "🔥 고강도 운동이었어요!"

    # PR 여부
    pr_text = ""
    if activity.get("pr_rank") == 1:
        pr_text = "\n🏆 역대 최고 페이스!"
    elif activity.get("pr_rank"):
        pr_text = f"\n🥈 기록 순위 {activity['pr_rank']}위"

    # km별 구간
    splits_text = ""
    for s in activity.get("splits", []):
        splits_text += f"  {s['km']}km: {s['pace']} | 💓 {s['avg_heartrate']}bpm\n"
    weather_text = ""
    if weather:
        weather_text = f"🌤 {weather['sky']} {weather['temperature']}°C | 습도 {weather['humidity']}% | 바람 {weather['wind_speed']}m/s"

    message = f"""🏃 <b>러닝 완료!</b>

📅 {activity['date']}
📍 {activity['name']}
{weather_text}

📊 <b>운동 요약</b>
- 거리: <b>{activity['distance_km']} km</b>
- 시간: <b>{activity['moving_time']}</b>
- 페이스: <b>{activity['pace']}</b>
- 평균 심박: <b>{activity['avg_heartrate']} bpm</b>
- 최고 심박: {activity['max_heartrate']} bpm
- 케이던스: {activity['avg_cadence']} spm
- 칼로리: {activity['calories']} kcal
- 고도 상승: {activity['elevation_gain']} m
{pr_text}

{hr_comment}

📈 <b>구간별 분석</b>
{splits_text}"""

    return message.strip()