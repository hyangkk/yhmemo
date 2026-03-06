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

# CoinGecko 자산 ID 매핑
CRYPTO_IDS = {
    "비트코인": "bitcoin", "btc": "bitcoin", "bitcoin": "bitcoin",
    "이더리움": "ethereum", "eth": "ethereum", "ethereum": "ethereum",
    "금": "pax-gold", "gold": "pax-gold", "골드": "pax-gold",
    "리플": "ripple", "xrp": "ripple",
    "솔라나": "solana", "sol": "solana",
    "도지코인": "dogecoin", "doge": "dogecoin",
    "에이다": "cardano", "ada": "cardano",
}

# LS증권 클라이언트 (orchestrator에서 주입)
_ls_client = None

def set_ls_client(client):
    global _ls_client
    _ls_client = client

# 도구 정의 (LLM에게 알려줄 목록)
TOOL_DEFINITIONS = """사용 가능한 도구:
1. weather(location) - 실시간 날씨 조회. 예: weather("서울"), weather("부산")
2. search(query) - 웹 검색으로 최신 정보 조회. 예: search("테슬라 주가"), search("손흥민 경기결과")
3. exchange(from_currency, to_currency) - 환율 조회. 예: exchange("USD", "KRW")
4. now() - 현재 한국 시간
5. crypto(asset) - 암호화폐/금 현재가 + 24시간 변동. 예: crypto("비트코인"), crypto("금"), crypto("이더리움")
6. price_chart(asset, days) - 가격 추이 차트 데이터. 예: price_chart("비트코인", 30), price_chart("금", 7)
7. compare_assets(asset1, asset2, days) - 두 자산 가격 추이 비교. 예: compare_assets("금", "비트코인", 30)
8. stock_price(code) - 국내 주식 현재가 조회. 예: stock_price("005930") (삼성전자)
9. stock_buy(code, qty) - 주식 시장가 매수. 예: stock_buy("005930", 1) (삼성전자 1주 매수)
10. stock_sell(code, qty) - 주식 시장가 매도. 예: stock_sell("005930", 1)
11. stock_balance() - 주식 잔고/보유종목 조회
12. stock_buy_limit(code, qty, price) - 주식 지정가 매수. 예: stock_buy_limit("005930", 1, 55000)
13. stock_sell_limit(code, qty, price) - 주식 지정가 매도. 예: stock_sell_limit("005930", 1, 60000)

도구가 필요하면 반드시 이 형식으로 응답:
{"needs_tool": true, "tool_calls": [{"tool": "weather", "args": ["서울"]}]}

여러 도구 동시 호출 가능:
{"needs_tool": true, "tool_calls": [{"tool": "crypto", "args": ["비트코인"]}, {"tool": "crypto", "args": ["금"]}]}

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
        elif tool_name == "crypto":
            return await _crypto_price(args[0] if args else "비트코인")
        elif tool_name == "price_chart":
            asset = args[0] if args else "비트코인"
            days = int(args[1]) if len(args) > 1 else 30
            return await _price_chart(asset, days)
        elif tool_name == "compare_assets":
            a1 = args[0] if args else "금"
            a2 = args[1] if len(args) > 1 else "비트코인"
            days = int(args[2]) if len(args) > 2 else 30
            return await _compare_assets(a1, a2, days)
        elif tool_name == "stock_price":
            return await _stock_price(args[0] if args else "005930")
        elif tool_name == "stock_buy":
            return await _stock_buy(args[0], int(args[1]) if len(args) > 1 else 1)
        elif tool_name == "stock_sell":
            return await _stock_sell(args[0], int(args[1]) if len(args) > 1 else 1)
        elif tool_name == "stock_balance":
            return await _stock_balance()
        elif tool_name == "stock_buy_limit":
            return await _stock_buy(args[0], int(args[1]), int(args[2]), limit=True)
        elif tool_name == "stock_sell_limit":
            return await _stock_sell(args[0], int(args[1]), int(args[2]), limit=True)
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
    """다중 소스 웹 검색 (DDG HTML → DDG Lite → DDG Instant Answer)"""
    if not query:
        return "검색어가 없습니다"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
        results = []

        # 1차: DuckDuckGo HTML 버전 (가장 풍부한 결과)
        try:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={quote(query)}",
            )
            if resp.status_code == 200:
                html = resp.text
                # 제목 추출 (result__a 클래스)
                titles = re.findall(
                    r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>',
                    html, re.DOTALL,
                )
                # 스니펫 추출 (result__snippet 클래스 - <a> 태그 안에 있음)
                snippets = re.findall(
                    r'class="result__snippet" href="[^"]+"[^>]*>(.*?)</a>',
                    html, re.DOTALL,
                )
                for i, (raw_url, raw_title) in enumerate(titles[:7]):
                    title = re.sub(r'<.*?>', '', raw_title).strip()
                    snippet = re.sub(r'<.*?>', '', snippets[i]).strip() if i < len(snippets) else ""
                    # URL 디코딩 (DDG 리다이렉트 URL에서 실제 URL 추출)
                    url_match = re.search(r'uddg=([^&]+)', raw_url)
                    url = quote(url_match.group(1), safe='/:?=&%') if url_match else raw_url
                    from urllib.parse import unquote
                    url = unquote(url)
                    if title and (snippet or url):
                        results.append(f"• {title}\n  {snippet[:200]}\n  🔗 {url[:100]}")
        except Exception as e:
            logger.debug(f"DDG HTML search error: {e}")

        if results:
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(results[:5])

        # 2차: DuckDuckGo Lite (텍스트 기반)
        try:
            resp = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": "kr-kr"},
            )
            if resp.status_code == 200:
                html = resp.text
                snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', html, re.DOTALL)
                links = re.findall(r'<a rel="nofollow" href="(.*?)" class=\'result-link\'>(.*?)</a>', html)
                for i, (link, title) in enumerate(links[:5]):
                    snippet = snippets[i].strip() if i < len(snippets) else ""
                    snippet = re.sub(r'<.*?>', '', snippet).strip()
                    title = re.sub(r'<.*?>', '', title).strip()
                    if title:
                        results.append(f"• {title}\n  {snippet[:200]}")
        except Exception as e:
            logger.debug(f"DDG Lite search error: {e}")

        if results:
            return f"'{query}' 검색 결과:\n\n" + "\n\n".join(results[:5])

        # 3차: DuckDuckGo Instant Answer API
        try:
            api_url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
            resp = await client.get(api_url)
            data = resp.json()
            answer = data.get("Answer", "")
            abstract = data.get("AbstractText", "")
            # Related topics도 활용
            related = data.get("RelatedTopics", [])
            if answer:
                return f"'{query}': {answer}"
            if abstract:
                return f"'{query}' 관련:\n{abstract}"
            if related:
                items = []
                for r in related[:5]:
                    if isinstance(r, dict) and "Text" in r:
                        items.append(f"• {r['Text'][:200]}")
                if items:
                    return f"'{query}' 관련 정보:\n\n" + "\n".join(items)
        except Exception as e:
            logger.debug(f"DDG API error: {e}")

        return f"'{query}'에 대한 검색 결과를 가져오지 못했습니다. 다른 키워드로 시도해보세요."


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


def _resolve_crypto_id(name: str) -> str:
    """자산명 → CoinGecko ID"""
    key = name.strip().lower()
    return CRYPTO_IDS.get(key, key)


async def _crypto_price(asset: str) -> str:
    """암호화폐/금 현재가 조회 (CoinGecko)"""
    coin_id = _resolve_crypto_id(asset)

    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd,krw&include_24hr_change=true&include_market_cap=true"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        if coin_id not in data:
            return f"'{asset}'을(를) 찾을 수 없습니다"

        info = data[coin_id]
        usd = info.get("usd", 0)
        krw = info.get("krw", 0)
        change_24h = info.get("usd_24h_change", 0)
        market_cap = info.get("usd_market_cap", 0)

        arrow = "📈" if change_24h >= 0 else "📉"
        sign = "+" if change_24h >= 0 else ""

        # 금은 온스당 가격이므로 추가 안내
        gold_note = "\n(PAX Gold 기준, 금 1온스 ≈ 토큰 1개)" if coin_id == "pax-gold" else ""

        return f"""{arrow} {asset} 현재가
💰 ${usd:,.2f} (₩{krw:,.0f})
📊 24시간 변동: {sign}{change_24h:.2f}%
🏦 시가총액: ${market_cap/1e9:,.1f}B{gold_note}"""


async def _price_chart(asset: str, days: int = 30) -> str:
    """가격 추이 데이터 (텍스트 차트)"""
    coin_id = _resolve_crypto_id(asset)
    days = min(days, 365)

    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=daily"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        prices = data.get("prices", [])
        if not prices:
            return f"'{asset}' 가격 데이터를 가져올 수 없습니다"

        # 주요 포인트 추출
        first_price = prices[0][1]
        last_price = prices[-1][1]
        max_price = max(p[1] for p in prices)
        min_price = min(p[1] for p in prices)
        change_pct = ((last_price - first_price) / first_price) * 100

        # 텍스트 미니 차트 (블록 문자)
        chart_data = [p[1] for p in prices]
        chart_min = min(chart_data)
        chart_max = max(chart_data)
        chart_range = chart_max - chart_min if chart_max != chart_min else 1
        bars = "▁▂▃▄▅▆▇█"
        # 20개 포인트로 리샘플링
        step = max(1, len(chart_data) // 20)
        sampled = chart_data[::step][:20]
        chart_str = "".join(bars[min(int((v - chart_min) / chart_range * 7), 7)] for v in sampled)

        sign = "+" if change_pct >= 0 else ""
        arrow = "📈" if change_pct >= 0 else "📉"

        from datetime import datetime as dt
        start_date = dt.fromtimestamp(prices[0][0] / 1000, tz=KST).strftime("%m/%d")
        end_date = dt.fromtimestamp(prices[-1][0] / 1000, tz=KST).strftime("%m/%d")

        return f"""{arrow} {asset} {days}일 가격 추이
{chart_str}
{start_date} ────────── {end_date}

💰 현재: ${last_price:,.2f}
📊 변동: {sign}{change_pct:.1f}%
⬆️ 최고: ${max_price:,.2f}
⬇️ 최저: ${min_price:,.2f}"""


async def _compare_assets(asset1: str, asset2: str, days: int = 30) -> str:
    """두 자산 가격 추이 비교"""
    id1 = _resolve_crypto_id(asset1)
    id2 = _resolve_crypto_id(asset2)
    days = min(days, 365)

    async with httpx.AsyncClient(timeout=10.0) as client:
        url1 = f"https://api.coingecko.com/api/v3/coins/{id1}/market_chart?vs_currency=usd&days={days}&interval=daily"
        url2 = f"https://api.coingecko.com/api/v3/coins/{id2}/market_chart?vs_currency=usd&days={days}&interval=daily"

        r1 = await client.get(url1)
        r2 = await client.get(url2)
        r1.raise_for_status()
        r2.raise_for_status()

        prices1 = r1.json().get("prices", [])
        prices2 = r2.json().get("prices", [])

        if not prices1 or not prices2:
            return "가격 데이터를 가져올 수 없습니다"

        # 수익률 계산
        base1, last1 = prices1[0][1], prices1[-1][1]
        base2, last2 = prices2[0][1], prices2[-1][1]
        ret1 = ((last1 - base1) / base1) * 100
        ret2 = ((last2 - base2) / base2) * 100

        # 미니 차트 (수익률 기준으로 정규화)
        bars = "▁▂▃▄▅▆▇█"

        def make_chart(prices_list):
            data = [p[1] for p in prices_list]
            # 수익률 기준
            base = data[0]
            returns = [(v / base - 1) * 100 for v in data]
            r_min, r_max = min(returns), max(returns)
            r_range = r_max - r_min if r_max != r_min else 1
            step = max(1, len(returns) // 20)
            sampled = returns[::step][:20]
            return "".join(bars[min(int((v - r_min) / r_range * 7), 7)] for v in sampled)

        chart1 = make_chart(prices1)
        chart2 = make_chart(prices2)

        sign1 = "+" if ret1 >= 0 else ""
        sign2 = "+" if ret2 >= 0 else ""
        winner = asset1 if ret1 > ret2 else asset2

        from datetime import datetime as dt
        start = dt.fromtimestamp(prices1[0][0] / 1000, tz=KST).strftime("%m/%d")
        end = dt.fromtimestamp(prices1[-1][0] / 1000, tz=KST).strftime("%m/%d")

        return f"""📊 {asset1} vs {asset2} ({days}일 비교, {start}~{end})

{asset1}: {chart1}
  ${base1:,.2f} → ${last1:,.2f} ({sign1}{ret1:.1f}%)

{asset2}: {chart2}
  ${base2:,.2f} → ${last2:,.2f} ({sign2}{ret2:.1f}%)

🏆 승자: {winner} ({sign1 if winner == asset1 else sign2}{ret1 if winner == asset1 else ret2:.1f}%)"""


# ── 주식 매매 도구 ──────────────────────────────────────

async def _stock_price(code: str) -> str:
    """국내 주식 현재가 조회"""
    if not _ls_client:
        return "LS증권 연동이 설정되지 않았습니다 (LS_APP_KEY 환경변수 필요)"
    try:
        data = await _ls_client.get_price(code)
        name = data.get("종목명", code)
        price = data.get("현재가", 0)
        change = data.get("전일대비", 0)
        rate = data.get("등락률", 0)
        vol = data.get("거래량", 0)
        bid = data.get("매수호가1", 0)
        ask = data.get("매도호가1", 0)
        arrow = "📈" if change >= 0 else "📉"
        sign = "+" if change >= 0 else ""
        return f"""{arrow} {name} ({code})
💰 현재가: {price:,}원 ({sign}{change:,}원, {sign}{rate:.2f}%)
📊 거래량: {vol:,}
🔵 매수호가: {bid:,}원 | 🔴 매도호가: {ask:,}원"""
    except Exception as e:
        return f"시세 조회 실패: {e}"


async def _stock_buy(code: str, qty: int, price: int = 0, limit: bool = False) -> str:
    """주식 매수"""
    if not _ls_client:
        return "LS증권 연동이 설정되지 않았습니다"
    try:
        order_type = "00" if limit else "03"
        result = await _ls_client.buy(code, qty, price=price, order_type=order_type)
        status = result.get("결과", "")
        order_no = result.get("주문번호", "")
        price_str = f"{price:,}원" if price else "시장가"
        mode = "지정가" if limit else "시장가"
        return f"""✅ 매수 주문 ({mode})
종목: {code} | 수량: {qty}주 | 가격: {price_str}
결과: {status} | 주문번호: {order_no}"""
    except Exception as e:
        return f"매수 주문 실패: {e}"


async def _stock_sell(code: str, qty: int, price: int = 0, limit: bool = False) -> str:
    """주식 매도"""
    if not _ls_client:
        return "LS증권 연동이 설정되지 않았습니다"
    try:
        order_type = "00" if limit else "03"
        result = await _ls_client.sell(code, qty, price=price, order_type=order_type)
        status = result.get("결과", "")
        order_no = result.get("주문번호", "")
        price_str = f"{price:,}원" if price else "시장가"
        mode = "지정가" if limit else "시장가"
        return f"""✅ 매도 주문 ({mode})
종목: {code} | 수량: {qty}주 | 가격: {price_str}
결과: {status} | 주문번호: {order_no}"""
    except Exception as e:
        return f"매도 주문 실패: {e}"


async def _stock_balance() -> str:
    """주식 잔고 조회"""
    if not _ls_client:
        return "LS증권 연동이 설정되지 않았습니다"
    try:
        data = await _ls_client.get_balance()
        summary = data.get("summary", {})
        holdings = data.get("holdings", [])

        total = summary.get("추정순자산", 0)
        profit = summary.get("추정손익", 0)
        rate = summary.get("수익률", 0)
        sign = "+" if profit >= 0 else ""

        lines = [f"💼 주식 잔고"]
        lines.append(f"💰 총 평가: {total:,}원 ({sign}{profit:,}원, {sign}{rate:.2f}%)")

        if holdings:
            lines.append(f"\n📋 보유종목 ({len(holdings)}개):")
            for h in holdings:
                name = h.get("종목명", "")
                code = h.get("종목코드", "")
                qty = h.get("잔고수량", 0)
                avg = h.get("매입단가", 0)
                cur = h.get("현재가", 0)
                pl = h.get("평가손익", 0)
                pl_rate = h.get("수익률", 0)
                s = "+" if pl >= 0 else ""
                lines.append(f"  • {name}({code}): {qty}주 | 평균 {avg:,}원 → 현재 {cur:,}원 ({s}{pl:,}원, {s}{pl_rate:.2f}%)")
        else:
            lines.append("\n보유종목 없음")

        return "\n".join(lines)
    except Exception as e:
        return f"잔고 조회 실패: {e}"
