"""
실시간 도구 모음 - 봇이 실시간 정보를 가져올 수 있는 도구들

날씨(Open-Meteo), 웹검색(DuckDuckGo), 환율, 시간 등
"""

import re
import httpx
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

logger = logging.getLogger("tools")
KST = timezone(timedelta(hours=9))

# WMO 날씨 코드 → 한국어
WMO_CODES = {
    0: "맑음 ☀️", 1: "대체로 맑음 🌤️", 2: "약간 흐림 ⛅", 3: "흐림 ☁️",
    45: "안개 🌫️", 48: "짙은 안개 🌫️",
    51: "가벼운 이슬비 🌦️", 53: "이슬비 🌦️", 55: "강한 이슬비 🌧️",
    61: "약한 비 🌧️", 63: "비 🌧️", 65: "강한 비 🌧️",
    71: "약한 눈 🌨️", 73: "눈 🌨️", 75: "강한 눈 ❄️",
    80: "소나기 🌦️", 81: "강한 소나기 🌧️", 82: "폭우 ⛈️",
    95: "뇌우 ⛈️", 96: "우박 뇌우 ⛈️", 99: "강한 우박 뇌우 ⛈️",
}

# 주요 도시 좌표
CITY_COORDS = {
    "서울": (37.5665, 126.978), "부산": (35.1796, 129.0756), "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014), "대전": (36.3504, 127.3845), "광주": (35.1595, 126.8526),
    "수원": (37.2636, 127.0286), "울산": (35.5384, 129.3114), "세종": (36.48, 127.26),
    "제주": (33.4996, 126.5312), "춘천": (37.8813, 127.7298), "강릉": (37.7519, 128.8761),
    "전주": (35.8242, 127.148), "창원": (35.2281, 128.6811), "포항": (36.019, 129.3435),
    "경주": (35.8562, 129.2247), "여수": (34.7604, 127.6622), "속초": (38.207, 128.5918),
    "tokyo": (35.6762, 139.6503), "osaka": (34.6937, 135.5023),
    "new york": (40.7128, -74.006), "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522), "la": (34.0522, -118.2437),
    "san francisco": (37.7749, -122.4194), "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737), "singapore": (1.3521, 103.8198),
    "bangkok": (13.7563, 100.5018), "sydney": (-33.8688, 151.2093),
}

# 도구 정의 (LLM에게 알려줄 목록)
TOOL_DEFINITIONS = """사용 가능한 도구:
1. weather(location) - 실시간 날씨 조회. 예: weather("서울"), weather("부산")
2. search(query) - 웹 검색으로 최신 정보 조회. 예: search("테슬라 주가"), search("손흥민 경기결과")
3. exchange(from_currency, to_currency) - 환율 조회. 예: exchange("USD", "KRW")
4. now() - 현재 한국 시간

도구가 필요하면 반드시 이 형식으로 응답:
{"needs_tool": true, "tool_calls": [{"tool": "weather", "args": ["서울"]}]}

여러 도구 동시 호출 가능:
{"needs_tool": true, "tool_calls": [{"tool": "weather", "args": ["서울"]}, {"tool": "now", "args": []}]}

도구 없이 답할 수 있으면:
{"needs_tool": false}"""


async def execute_tool(tool_name: str, args: list) -> str:
    """도구 실행하고 결과 문자열 반환"""
    try:
        if tool_name == "weather":
            return await _weather(args[0] if args else "서울")
        elif tool_name == "search":
            return await _web_search(args[0] if args else "")
        elif tool_name == "exchange":
            from_c = args[0] if len(args) > 0 else "USD"
            to_c = args[1] if len(args) > 1 else "KRW"
            return await _exchange_rate(from_c, to_c)
        elif tool_name == "now":
            return _current_time()
        else:
            return f"알 수 없는 도구: {tool_name}"
    except Exception as e:
        logger.error(f"Tool '{tool_name}' error: {e}")
        return f"도구 실행 오류: {str(e)[:200]}"


async def execute_tool_calls(tool_calls: list) -> str:
    """여러 도구 호출 실행, 결과 합쳐서 반환"""
    results = []
    for call in tool_calls:
        tool = call.get("tool", "")
        args = call.get("args", [])
        result = await execute_tool(tool, args)
        results.append(f"[{tool}] {result}")
    return "\n\n".join(results)


# ── 개별 도구 구현 ──────────────────────────────────────

def _resolve_coords(location: str) -> tuple[float, float, str]:
    """도시명 → 좌표 변환"""
    loc = location.strip().lower()
    for name, coords in CITY_COORDS.items():
        if name in loc or loc in name:
            return coords[0], coords[1], name
    # 기본값 서울
    return 37.5665, 126.978, location


async def _weather(location: str) -> str:
    """Open-Meteo API로 실시간 날씨 조회 (API 키 불필요)"""
    lat, lon, city_name = _resolve_coords(location)

    async with httpx.AsyncClient(timeout=10.0) as client:
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,weather_code,"
            f"wind_speed_10m,apparent_temperature,precipitation"
            f"&daily=temperature_2m_max,temperature_2m_min,sunrise,sunset,"
            f"uv_index_max,precipitation_sum,weather_code"
            f"&timezone=Asia/Seoul&forecast_days=3"
        )
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        cur = data.get("current", {})
        daily = data.get("daily", {})

        temp = cur.get("temperature_2m", "?")
        feels = cur.get("apparent_temperature", "?")
        humidity = cur.get("relative_humidity_2m", "?")
        wind = cur.get("wind_speed_10m", "?")
        precip = cur.get("precipitation", 0)
        wmo = cur.get("weather_code", 0)
        desc = WMO_CODES.get(wmo, f"코드 {wmo}")

        # 오늘
        max_t = daily.get("temperature_2m_max", ["?"])[0]
        min_t = daily.get("temperature_2m_min", ["?"])[0]
        sunrise = daily.get("sunrise", [""])[0]
        sunset = daily.get("sunset", [""])[0]
        uv = daily.get("uv_index_max", ["?"])[0]
        daily_precip = daily.get("precipitation_sum", [0])[0]

        # 시간 파싱
        sr = sunrise.split("T")[1][:5] if "T" in str(sunrise) else sunrise
        ss = sunset.split("T")[1][:5] if "T" in str(sunset) else sunset

        # 내일/모레 예보
        forecast_lines = []
        days_kr = ["오늘", "내일", "모레"]
        for i in range(1, min(3, len(daily.get("time", [])))):
            d_date = daily["time"][i]
            d_max = daily["temperature_2m_max"][i]
            d_min = daily["temperature_2m_min"][i]
            d_wmo = daily["weather_code"][i]
            d_desc = WMO_CODES.get(d_wmo, "")
            d_precip = daily.get("precipitation_sum", [0])[i] if i < len(daily.get("precipitation_sum", [])) else 0
            label = days_kr[i] if i < len(days_kr) else d_date
            rain_info = f" 강수 {d_precip}mm" if d_precip > 0 else ""
            forecast_lines.append(f"  {label}: {d_min}°C ~ {d_max}°C {d_desc}{rain_info}")

        forecast = "\n".join(forecast_lines)
        rain_info = f"\n🌧️ 현재 강수: {precip}mm / 오늘 총 {daily_precip}mm" if precip > 0 or daily_precip > 0 else ""

        return f"""📍 {city_name} 현재 날씨
🌡️ {temp}°C (체감 {feels}°C) | {desc}
📊 최저 {min_t}°C / 최고 {max_t}°C
💧 습도: {humidity}% | 🌬️ 풍속: {wind}km/h{rain_info}
☀️ UV {uv} | 🌅 {sr} ~ 🌇 {ss}

📅 예보:
{forecast}"""


async def _web_search(query: str) -> str:
    """DuckDuckGo로 웹 검색"""
    if not query:
        return "검색어가 없습니다"

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        # DuckDuckGo Lite
        resp = await client.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": query, "kl": "kr-kr"},
        )
        resp.raise_for_status()
        html = resp.text

        results = []
        snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html, re.DOTALL)
        links = re.findall(r'<a rel="nofollow" href="(.*?)" class=\'result-link\'>(.*?)</a>', html)

        for i, (link, title) in enumerate(links[:5]):
            snippet = snippets[i].strip() if i < len(snippets) else ""
            snippet = re.sub(r'<.*?>', '', snippet).strip()
            title = re.sub(r'<.*?>', '', title).strip()
            results.append(f"• {title}\n  {snippet}")

        if results:
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(results)

        # 폴백: Instant Answer API
        api_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        resp2 = await client.get(api_url)
        data = resp2.json()
        abstract = data.get("AbstractText", "")
        answer = data.get("Answer", "")
        if answer:
            return f"'{query}': {answer}"
        if abstract:
            return f"'{query}' 관련:\n{abstract}"
        return f"'{query}'에 대한 검색 결과를 가져오지 못했습니다."


async def _exchange_rate(from_currency: str, to_currency: str) -> str:
    """환율 조회"""
    from_c = from_currency.upper()
    to_c = to_currency.upper()

    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"https://open.er-api.com/v6/latest/{from_c}"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        rates = data.get("rates", {})
        if to_c in rates:
            rate = rates[to_c]
            now = _current_time()
            return f"💱 환율 ({now} 기준)\n1 {from_c} = {rate:,.2f} {to_c}"
        else:
            return f"'{to_c}' 통화를 찾을 수 없습니다"


def _current_time() -> str:
    """현재 한국 시간"""
    now = datetime.now(KST)
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    wd = weekdays[now.weekday()]
    return f"{now.strftime('%Y-%m-%d')} ({wd}) {now.strftime('%H:%M:%S')} KST"
