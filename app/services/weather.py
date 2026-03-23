import httpx
import math
from datetime import datetime, timedelta
import app.config as config


def get_base_time() -> tuple[str, str]:
    """
    기상청 API는 특정 시간에만 예보를 업데이트해요
    매일 02, 05, 08, 11, 14, 17, 20, 23시 발표
    현재 시각 기준으로 가장 최근 발표 시각 반환
    """
    now = datetime.now()
    base_times = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]

    base_date = now.strftime("%Y%m%d")
    base_time = "2300"

    for bt in base_times:
        hour = int(bt[:2])
        minute = int(bt[2:])
        if now >= now.replace(hour=hour, minute=minute, second=0):
            base_time = bt
        else:
            break

    # 자정 이후 02시 전이면 전날 23시 예보 사용
    if now.hour < 2:
        yesterday = now - timedelta(days=1)
        base_date = yesterday.strftime("%Y%m%d")
        base_time = "2300"

    return base_date, base_time


async def get_weather(lat: float = None, lon: float = None) -> dict:
    """
    기상청 단기예보 API로 날씨 데이터 가져오기
    lat, lon이 있으면 위경도로 격자 변환
    없으면 config 기본값 사용
    """
    if lat and lon:
        nx, ny = latlon_to_grid(lat, lon)
        print(f"위경도 변환: ({lat}, {lon}) → 격자 ({nx}, {ny})")
    else:
        nx = config.WEATHER_NX
        ny = config.WEATHER_NY

    base_date, base_time = get_base_time()

    url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={
                "serviceKey": config.WEATHER_API_KEY,
                "pageNo": 1,
                "numOfRows": 100,
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
            }
        )

    if response.status_code != 200:
        print(f"날씨 API 에러: {response.status_code}")
        return {}

    data = response.json()
    items = data["response"]["body"]["items"]["item"]

    # 필요한 데이터만 파싱
    weather = {}
    for item in items:
        category = item["category"]
        value = item["fcstValue"]
        time = item["fcstTime"]

        # 가장 가까운 시간대 데이터만 저장
        if time not in weather:
            weather[time] = {}
        weather[time][category] = value

    # 첫 번째 시간대 데이터 반환
    first_time = sorted(weather.keys())[0]
    raw = weather[first_time]

    return parse_weather(raw)


def parse_weather(raw: dict) -> dict:
    """
    기상청 카테고리 코드를 사람이 읽기 좋게 변환

    주요 카테고리:
    TMP  → 기온 (°C)
    WSD  → 풍속 (m/s)
    PTY  → 강수형태 (0:없음 1:비 2:비/눈 3:눈 4:소나기)
    POP  → 강수확률 (%)
    REH  → 습도 (%)
    SKY  → 하늘상태 (1:맑음 3:구름많음 4:흐림)
    """
    pty_map = {
        "0": "없음",
        "1": "비",
        "2": "비/눈",
        "3": "눈",
        "4": "소나기"
    }

    sky_map = {
        "1": "맑음",
        "3": "구름많음",
        "4": "흐림"
    }

    pty = raw.get("PTY", "0")
    sky = raw.get("SKY", "1")
    wind_speed = float(raw.get("WSD", 0))

    # 러닝 조건 판단
    running_condition = evaluate_running_condition(
        pty=pty,
        wind_speed=wind_speed,
        temp=float(raw.get("TMP", 20)),
        humidity=int(raw.get("REH", 50)),
    )

    return {
        "temperature": raw.get("TMP", "N/A"),
        "humidity": raw.get("REH", "N/A"),
        "wind_speed": wind_speed,
        "precipitation": pty_map.get(pty, "없음"),
        "sky": sky_map.get(sky, "맑음"),
        "rain_probability": raw.get("POP", "0"),
        "running_condition": running_condition,
    }


def evaluate_running_condition(pty: str, wind_speed: float, 
                                temp: float, humidity: int) -> str:
    """
    러닝하기 좋은 조건인지 판단
    나중에 Ollama로 대체 예정
    """
    if pty in ("1", "2", "4"):  # 비, 비/눈, 소나기
        return "나쁨"
    if pty == "3":  # 눈
        return "나쁨"
    if wind_speed >= 9:  # 강풍 (9m/s 이상)
        return "나쁨"
    if temp <= 0 or temp >= 33:  # 너무 춥거나 더울 때
        return "나쁨"
    if humidity >= 85:  # 습도 너무 높을 때
        return "보통"
    if wind_speed >= 5:  # 약간 바람
        return "보통"
    return "좋음"


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """
    위경도 → 기상청 격자 좌표 변환
    기상청 공식 변환 공식
    """
    RE = 6371.00877
    GRID = 5.0
    SLAT1 = 30.0
    SLAT2 = 60.0
    OLON = 126.0
    OLAT = 38.0
    XO = 43
    YO = 136

    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = math.pow(sf, sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / math.pow(ro, sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / math.pow(ra, sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + YO + 0.5)

    return nx, ny