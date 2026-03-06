"""
투자 에이전트 (Investment Agent)

역할:
- 주요 자산(비트코인, 이더리움, 금, 주요 암호화폐) 시세를 주기적으로 모니터링
- 급등/급락 감지 시 즉시 알림
- 매일 아침/저녁 시장 브리핑 제공
- AI 기반 시장 분석 및 인사이트 생성
- Fear & Greed Index 등 시장 심리 분석

채널: #ai-invest
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INVEST_STATE_FILE = os.path.join(DATA_DIR, "invest_state.json")

# 모니터링 대상 자산
WATCH_ASSETS = {
    "bitcoin": {"name": "비트코인", "symbol": "BTC", "emoji": "🟠"},
    "ethereum": {"name": "이더리움", "symbol": "ETH", "emoji": "🔷"},
    "pax-gold": {"name": "금(PAXG)", "symbol": "GOLD", "emoji": "🥇"},
    "solana": {"name": "솔라나", "symbol": "SOL", "emoji": "🟣"},
    "ripple": {"name": "리플", "symbol": "XRP", "emoji": "⚪"},
}

# 급등/급락 기준 (%)
ALERT_THRESHOLD = 5.0  # 24시간 내 5% 이상 변동


class InvestmentAgent(BaseAgent):
    """투자 시장 모니터링 및 AI 인사이트 에이전트"""

    def __init__(self, target_channel: str = "ai-invest", **kwargs):
        super().__init__(
            name="investment",
            description="암호화폐/금 시장을 모니터링하고 AI 인사이트를 제공하는 투자 에이전트",
            slack_channel=target_channel,
            loop_interval=600,  # 10분마다 체크
            **kwargs,
        )
        self._target_channel = target_channel
        self._state = self._load_state()
        self._last_briefing_hour: int | None = self._state.get("last_briefing_hour")
        self._last_prices: dict = self._state.get("last_prices", {})
        self._alerted_assets: dict = self._state.get("alerted_assets", {})

    # ── 상태 관리 ──────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(INVEST_STATE_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        state = {
            "last_briefing_hour": self._last_briefing_hour,
            "last_prices": self._last_prices,
            "alerted_assets": self._alerted_assets,
            "updated_at": datetime.now(KST).isoformat(),
        }
        with open(INVEST_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, ensure_ascii=False, indent=2))

    # ── Observe: 시장 데이터 수집 ─────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "prices": {},
            "fear_greed": None,
            "alerts": [],
        }

        # 1. 모든 자산 현재가 조회
        try:
            prices = await self._fetch_all_prices()
            context["prices"] = prices
        except Exception as e:
            logger.error(f"[investment] Price fetch error: {e}")
            return None

        # 2. Fear & Greed Index
        try:
            fg = await self._fetch_fear_greed()
            context["fear_greed"] = fg
        except Exception as e:
            logger.debug(f"[investment] Fear & Greed fetch error: {e}")

        # 3. 급등/급락 감지
        for coin_id, data in prices.items():
            change_24h = data.get("change_24h", 0)
            if abs(change_24h) >= ALERT_THRESHOLD:
                # 같은 자산에 대해 1시간 이내 중복 알림 방지
                last_alert = self._alerted_assets.get(coin_id, "")
                if last_alert:
                    try:
                        last_dt = datetime.fromisoformat(last_alert)
                        if (now - last_dt).total_seconds() < 3600:
                            continue
                    except (ValueError, TypeError):
                        pass
                context["alerts"].append({
                    "coin_id": coin_id,
                    "name": WATCH_ASSETS.get(coin_id, {}).get("name", coin_id),
                    "change_24h": change_24h,
                    "price_usd": data.get("usd", 0),
                    "price_krw": data.get("krw", 0),
                })

        # 4. 브리핑 시간 체크 (아침 8시, 저녁 21시)
        context["is_briefing_time"] = (
            now.hour in (8, 21) and self._last_briefing_hour != now.hour
        )

        return context

    # ── Think: AI 분석 ────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        actions = []

        # 급등/급락 알림
        if context.get("alerts"):
            actions.append({"type": "alert", "data": context["alerts"]})

        # 정시 브리핑
        if context.get("is_briefing_time"):
            actions.append({
                "type": "briefing",
                "data": {
                    "prices": context["prices"],
                    "fear_greed": context["fear_greed"],
                    "hour": context["current_hour"],
                },
            })

        if not actions:
            # 가격 업데이트만 저장
            self._last_prices = context.get("prices", {})
            self._save_state()
            return None

        return {"actions": actions, "context": context}

    # ── Act: 알림/브리핑 전송 ─────────────────────────

    async def act(self, decision: dict):
        context = decision.get("context", {})

        for action in decision.get("actions", []):
            try:
                if action["type"] == "alert":
                    await self._send_alerts(action["data"])
                elif action["type"] == "briefing":
                    await self._send_market_briefing(action["data"])
            except Exception as e:
                logger.error(f"[investment] Act error ({action['type']}): {e}")

        # 상태 업데이트
        self._last_prices = context.get("prices", {})
        if context.get("is_briefing_time"):
            self._last_briefing_hour = context["current_hour"]
        self._save_state()

    # ── 데이터 수집 ───────────────────────────────────

    async def _fetch_all_prices(self) -> dict:
        """모든 감시 자산의 현재가 조회"""
        import httpx
        coin_ids = ",".join(WATCH_ASSETS.keys())
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={coin_ids}"
            f"&vs_currencies=usd,krw"
            f"&include_24hr_change=true"
            f"&include_market_cap=true"
            f"&include_24hr_vol=true"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        result = {}
        for coin_id, info in data.items():
            result[coin_id] = {
                "usd": info.get("usd", 0),
                "krw": info.get("krw", 0),
                "change_24h": info.get("usd_24h_change", 0),
                "market_cap": info.get("usd_market_cap", 0),
                "volume_24h": info.get("usd_24h_vol", 0),
            }
        return result

    async def _fetch_fear_greed(self) -> dict | None:
        """Crypto Fear & Greed Index 조회"""
        import httpx
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        items = data.get("data", [])
        if items:
            return {
                "value": int(items[0].get("value", 50)),
                "classification": items[0].get("value_classification", "Neutral"),
            }
        return None

    # ── 알림 전송 ─────────────────────────────────────

    async def _send_alerts(self, alerts: list):
        """급등/급락 알림"""
        now = datetime.now(KST)

        for alert in alerts:
            coin_id = alert["coin_id"]
            info = WATCH_ASSETS.get(coin_id, {})
            emoji = info.get("emoji", "💰")
            name = alert["name"]
            change = alert["change_24h"]
            usd = alert["price_usd"]
            krw = alert["price_krw"]

            direction = "급등" if change > 0 else "급락"
            sign = "+" if change > 0 else ""
            alert_emoji = "🚀" if change > 0 else "🔻"

            msg = (
                f"{alert_emoji} *{name} {direction} 알림!*\n\n"
                f"{emoji} *{name}* ({info.get('symbol', '')})\n"
                f"💰 ${usd:,.2f} (₩{krw:,.0f})\n"
                f"📊 24시간 변동: *{sign}{change:.2f}%*\n\n"
                f"_{now.strftime('%H:%M')} KST_"
            )

            await self.say(msg, self._target_channel)
            self._alerted_assets[coin_id] = now.isoformat()

        self._save_state()

    async def _send_market_briefing(self, data: dict):
        """시장 브리핑 전송"""
        prices = data.get("prices", {})
        fear_greed = data.get("fear_greed")
        hour = data.get("hour", 0)

        greeting = "모닝 마켓 브리핑" if hour < 12 else "이브닝 마켓 브리핑"
        now = datetime.now(KST)

        # 가격 테이블
        lines = [f"📊 *{greeting}* ({now.strftime('%m/%d %H:%M')} KST)\n"]

        for coin_id, info in WATCH_ASSETS.items():
            if coin_id not in prices:
                continue
            p = prices[coin_id]
            emoji = info["emoji"]
            name = info["name"]
            symbol = info["symbol"]
            usd = p["usd"]
            change = p.get("change_24h", 0)
            sign = "+" if change >= 0 else ""
            arrow = "▲" if change >= 0 else "▼"

            lines.append(
                f"{emoji} *{name}* ({symbol}): ${usd:,.2f} {arrow}{sign}{change:.1f}%"
            )

        # Fear & Greed
        if fear_greed:
            val = fear_greed["value"]
            cls = fear_greed["classification"]
            fg_emoji = self._fg_emoji(val)
            lines.append(f"\n{fg_emoji} *Fear & Greed*: {val}/100 ({cls})")

        # AI 인사이트 생성
        try:
            insight = await self._generate_insight(prices, fear_greed)
            if insight:
                lines.append(f"\n💡 *AI 인사이트*\n{insight}")
        except Exception as e:
            logger.debug(f"[investment] Insight generation error: {e}")

        await self.say("\n".join(lines), self._target_channel)

    async def _generate_insight(self, prices: dict, fear_greed: dict | None) -> str:
        """AI로 시장 인사이트 생성"""
        price_summary = []
        for coin_id, info in WATCH_ASSETS.items():
            if coin_id not in prices:
                continue
            p = prices[coin_id]
            price_summary.append(
                f"{info['name']}: ${p['usd']:,.2f} (24h: {p.get('change_24h', 0):+.1f}%)"
            )

        fg_text = ""
        if fear_greed:
            fg_text = f"\nFear & Greed Index: {fear_greed['value']}/100 ({fear_greed['classification']})"

        prompt = f"""현재 암호화폐/금 시장 현황:
{chr(10).join(price_summary)}
{fg_text}

위 데이터를 바탕으로 2-3문장의 간결한 시장 인사이트를 한국어로 작성하세요.
- 투자 조언이 아닌 시장 관찰/분석
- 자산 간 상관관계나 트렌드 언급
- 마지막에 "투자 결정은 본인의 판단으로." 한 줄 추가"""

        return await self.ai_think(
            system_prompt="당신은 암호화폐/금 시장 분석가입니다. 객관적이고 간결하게 분석하세요.",
            user_prompt=prompt,
        )

    def _fg_emoji(self, value: int) -> str:
        if value <= 25:
            return "😱"  # Extreme Fear
        elif value <= 45:
            return "😰"  # Fear
        elif value <= 55:
            return "😐"  # Neutral
        elif value <= 75:
            return "😊"  # Greed
        else:
            return "🤑"  # Extreme Greed

    # ── 외부 작업 처리 ────────────────────────────────

    async def handle_external_task(self, task: TaskMessage):
        if task.task_type == "market_check":
            prices = await self._fetch_all_prices()
            return {"prices": prices}
        elif task.task_type == "quick_briefing":
            prices = await self._fetch_all_prices()
            fg = await self._fetch_fear_greed()
            await self._send_market_briefing({
                "prices": prices,
                "fear_greed": fg,
                "hour": datetime.now(KST).hour,
            })
            return {"status": "sent"}
        return await super().handle_external_task(task)
