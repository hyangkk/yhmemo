"""
스윙 트레이더 에이전트 - 금요일까지 평가액 극대화

24시간 상시 운영:
- 장중(09:00~15:30): 시세 모니터링 + AI 매매 판단 + 주문 실행
- 장외(15:30~09:00): 뉴스/공시 수집 + 영향 분석 + 다음날 전략 수립
- 장 오픈(08:50~09:05): 프리마켓 분석 + 오픈 대응

사이클: 수집 → 분석 → 판단 → 거래 → 보고 → 반복
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx
import feedparser

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 종목 설정
STOCK_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차",
    "000270": "기아", "006400": "삼성SDI", "035720": "카카오",
    "068270": "셀트리온", "003670": "포스코퓨처엠", "009150": "삼성전기",
    "105560": "KB금융", "051910": "LG화학", "066570": "LG전자",
    "035420": "NAVER", "028260": "삼성물산", "012330": "현대모비스",
    "055550": "신한지주", "373220": "LG에너지솔루션", "207940": "삼성바이오로직스",
}

STOCK_SECTORS = {
    "005930": "반도체", "000660": "반도체", "009150": "반도체",
    "005380": "자동차", "000270": "자동차", "012330": "자동차",
    "006400": "2차전지", "373220": "2차전지", "003670": "2차전지",
    "035720": "IT플랫폼", "035420": "IT플랫폼",
    "068270": "바이오", "207940": "바이오",
    "105560": "금융", "055550": "금융",
    "051910": "화학", "066570": "전자",
    "028260": "건설",
}

# 뉴스 소스
NEWS_SOURCES = {
    "증권뉴스": "https://news.google.com/rss/search?q=한국+증시+주식+코스피&hl=ko&gl=KR&ceid=KR:ko",
    "경제뉴스": "https://news.google.com/rss/search?q=한국+경제+금리+환율&hl=ko&gl=KR&ceid=KR:ko",
    "반도체": "https://news.google.com/rss/search?q=반도체+삼성전자+SK하이닉스+HBM&hl=ko&gl=KR&ceid=KR:ko",
    "미국증시": "https://news.google.com/rss/search?q=미국+증시+나스닥+S%26P500+트럼프&hl=ko&gl=KR&ceid=KR:ko",
    "밸류업": "https://news.google.com/rss/search?q=밸류업+자사주+배당+주주환원&hl=ko&gl=KR&ceid=KR:ko",
}

DEFAULT_CONFIG = {
    "target_date": "2026-03-13",           # 평가 목표일
    "scan_tickers": list(STOCK_NAMES.keys()),
    "max_position_pct": 35,                # 종목당 최대 비중 (%)
    "max_stocks": 8,                       # 최대 보유 종목
    "stop_loss_pct": -5.0,                 # 손절 (스윙이라 넓게)
    "market_loop_interval": 180,           # 장중 사이클 (3분)
    "offhours_loop_interval": 1800,        # 장외 사이클 (30분)
    "daily_max_trades": 10,                # 하루 최대 거래
}


class SwingTraderAgent(BaseAgent):
    """24시간 스윙 트레이딩 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, ls_client=None, **kwargs):
        super().__init__(
            name="swing_trader",
            description="금요일 평가액 극대화 - 24시간 뉴스/시세 모니터링 + AI 매매",
            loop_interval=60,  # 기본 1분, _adaptive_interval로 동적 조절
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self.ls = ls_client
        self.config = dict(DEFAULT_CONFIG)
        if os.environ.get("SWING_TARGET_DATE"):
            self.config["target_date"] = os.environ["SWING_TARGET_DATE"]

        # 상태
        self._cycle = 0
        self._daily_trade_count = 0
        self._last_date = ""
        self._holdings: dict[str, dict] = {}
        self._last_prices: dict[str, dict] = {}
        self._news_buffer: list[dict] = []       # 수집된 뉴스 버퍼
        self._seen_news: set[str] = set()         # 중복 방지
        self._overnight_plan: dict | None = None  # 장외 분석 결과
        self._last_report_hour = -1
        self._trade_log: list[dict] = []
        self._http = httpx.AsyncClient(timeout=15.0)
        self._enabled = os.environ.get("SWING_TRADER_ENABLED", "true").lower() == "true"

    def _now(self) -> datetime:
        return datetime.now(KST)

    def _is_market_hours(self) -> bool:
        now = self._now()
        if now.weekday() >= 5:
            return False
        return now.replace(hour=9, minute=0, second=0) <= now <= now.replace(hour=15, minute=30, second=0)

    def _is_pre_market(self) -> bool:
        """장 오픈 직전 (08:45~09:05)"""
        now = self._now()
        if now.weekday() >= 5:
            return False
        return now.replace(hour=8, minute=45, second=0) <= now <= now.replace(hour=9, minute=5, second=0)

    def _days_to_target(self) -> int:
        target = datetime.strptime(self.config["target_date"], "%Y-%m-%d").date()
        today = self._now().date()
        return (target - today).days

    def _adaptive_interval(self) -> int:
        """상황에 따라 루프 간격 동적 조절"""
        if self._is_market_hours():
            return self.config["market_loop_interval"]  # 3분
        if self._is_pre_market():
            return 60  # 1분 (장 오픈 전 집중)
        return self.config["offhours_loop_interval"]  # 30분

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        if not self._enabled:
            return None

        # 날짜 변경 시 카운터 리셋
        today = self._now().strftime("%Y-%m-%d")
        if today != self._last_date:
            self._last_date = today
            self._daily_trade_count = 0
            self._last_report_hour = -1

        self._cycle += 1
        self.loop_interval = self._adaptive_interval()

        context = {
            "cycle": self._cycle,
            "now": self._now().isoformat(),
            "is_market": self._is_market_hours(),
            "is_pre_market": self._is_pre_market(),
            "days_to_target": self._days_to_target(),
        }

        # 1) 뉴스/공시 수집 (항상)
        news = await self._collect_news()
        if news:
            self._news_buffer.extend(news)
            # 최근 50개만 유지
            self._news_buffer = self._news_buffer[-50:]
        context["new_news"] = news
        context["news_buffer"] = self._news_buffer[-20:]

        # 2) DART 공시 수집
        dart_items = await self._collect_dart()
        context["disclosures"] = dart_items

        # 3) 시세 + 잔고 (장중 또는 프리마켓)
        if self._is_market_hours() or self._is_pre_market():
            if self.ls and self.ls.is_configured:
                # 잔고
                balance = await self.ls.get_balance()
                self._holdings = {}
                for h in balance.get("holdings", []):
                    if h["잔고수량"] > 0:
                        self._holdings[h["종목코드"]] = h
                context["balance"] = balance
                context["holdings"] = self._holdings

                # 시세
                prices = {}
                tickers = set(self.config["scan_tickers"])
                tickers.update(self._holdings.keys())
                for code in tickers:
                    try:
                        p = await self.ls.get_price(code)
                        if not p.get("unavailable"):
                            prices[code] = p
                            self._last_prices[code] = p
                    except Exception as e:
                        logger.warning(f"[swing] 시세 실패 {code}: {e}")
                context["prices"] = prices

                # 분봉 (보유종목)
                if self._is_market_hours() and hasattr(self.ls, "get_minute_bars"):
                    trends = {}
                    for code in list(self._holdings.keys())[:5]:
                        try:
                            bars = await self.ls.get_minute_bars(code, interval=5, count=20)
                            if bars:
                                trends[code] = self.ls.detect_trend(bars)
                        except Exception:
                            pass
                    context["trends"] = trends

        # 4) 장외 시간 야간 플랜 저장
        if not self._is_market_hours() and self._overnight_plan:
            context["overnight_plan"] = self._overnight_plan

        return context

    async def _collect_news(self) -> list[dict]:
        """뉴스 RSS 수집"""
        items = []
        for name, url in NEWS_SOURCES.items():
            try:
                resp = await self._http.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; SwingTrader/1.0)"
                })
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:8]:
                    title = entry.get("title", "")
                    key = title[:50]
                    if key not in self._seen_news:
                        self._seen_news.add(key)
                        items.append({
                            "title": title,
                            "url": entry.get("link", ""),
                            "source": name,
                            "published": entry.get("published", ""),
                        })
            except Exception as e:
                logger.warning(f"[swing] RSS 수집 실패 ({name}): {e}")
        return items

    async def _collect_dart(self) -> list[dict]:
        """DART 공시 수집"""
        items = []
        dart_key = os.environ.get("DART_API_KEY", "")
        if not dart_key and self.supabase:
            try:
                resp = self.supabase.table("secrets_vault").select("value").eq("key", "DART_API_KEY").execute()
                if resp.data:
                    dart_key = resp.data[0].get("value", "")
            except Exception:
                pass

        if not dart_key:
            return items

        today = self._now().strftime("%Y%m%d")
        try:
            url = (
                f"https://opendart.fss.or.kr/api/list.json"
                f"?crtfc_key={dart_key}"
                f"&bgn_de={today}&end_de={today}"
                f"&page_count=50&sort=date&sort_mth=desc"
            )
            resp = await self._http.get(url)
            data = resp.json()
            if data.get("status") == "000":
                watchlist = set(self.config["scan_tickers"])
                for item in data.get("list", []):
                    sc = item.get("stock_code", "")
                    if sc in watchlist:
                        key = item.get("rcept_no", "")
                        if key not in self._seen_news:
                            self._seen_news.add(key)
                            items.append({
                                "title": f"[공시] {item.get('corp_name','')} - {item.get('report_nm','')}",
                                "stock_code": sc,
                                "source": "DART",
                                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={key}",
                            })
        except Exception as e:
            logger.warning(f"[swing] DART 수집 실패: {e}")
        return items

    # ── Think ──────────────────────────────────────────

    async def think(self, ctx: dict) -> dict | None:
        is_market = ctx.get("is_market", False)
        is_pre = ctx.get("is_pre_market", False)

        # 장중(09:00~15:30)에만 매매 판단
        if is_market:
            return await self._think_market(ctx)

        # 프리마켓(08:45~09:05): 분석 보고만 (매매는 장 오픈 후)
        if is_pre:
            return await self._think_pre_market(ctx)

        # 장외: 뉴스 분석만 (매매 없음)
        return await self._think_offhours(ctx)

    async def _think_market(self, ctx: dict) -> dict | None:
        """장중 매매 판단"""
        holdings = ctx.get("holdings", {})
        prices = ctx.get("prices", {})
        trends = ctx.get("trends", {})
        balance = ctx.get("balance", {})
        news = ctx.get("news_buffer", [])
        days_left = ctx.get("days_to_target", 99)

        if not prices:
            return None

        # 1) 손절 체크
        actions = []
        for code, h in holdings.items():
            pnl = h.get("수익률", 0)
            if pnl <= self.config["stop_loss_pct"]:
                actions.append({
                    "action": "sell", "code": code,
                    "qty": h["잔고수량"],
                    "reason": f"손절: {pnl:.1f}%",
                })

        # 2) AI 종합 판단
        if self._daily_trade_count < self.config["daily_max_trades"]:
            ai_actions = await self._ai_swing_decide(ctx)
            if ai_actions:
                actions.extend(ai_actions)

        if not actions:
            # 정시 보고 (매 시간)
            hour = self._now().hour
            if hour != self._last_report_hour and hour in [9, 10, 11, 12, 13, 14, 15]:
                self._last_report_hour = hour
                return {"type": "hourly_report", "ctx": ctx}
            return None

        return {"type": "trade", "actions": actions}

    async def _think_pre_market(self, ctx: dict) -> dict | None:
        """프리마켓 분석 (08:45~09:05)"""
        if self._overnight_plan and not self._overnight_plan.get("executed"):
            self._overnight_plan["executed"] = True
            return {"type": "pre_market", "plan": self._overnight_plan}
        return None

    async def _think_offhours(self, ctx: dict) -> dict | None:
        """장외 시간 뉴스 분석"""
        news = ctx.get("new_news", [])
        disclosures = ctx.get("disclosures", [])

        if not news and not disclosures:
            return None

        all_items = news + disclosures
        if len(all_items) < 3:
            return None  # 충분한 정보가 모일 때까지 대기

        return {"type": "overnight_analysis", "items": all_items, "ctx": ctx}

    async def _ai_swing_decide(self, ctx: dict) -> list[dict]:
        """AI 스윙 트레이딩 판단"""
        holdings = ctx.get("holdings", {})
        prices = ctx.get("prices", {})
        trends = ctx.get("trends", {})
        balance = ctx.get("balance", {})
        news = ctx.get("news_buffer", [])
        days_left = ctx.get("days_to_target", 99)

        summary = balance.get("summary", {})
        total_asset = summary.get("추정순자산", 0)
        total_pnl = summary.get("추정손익", 0)

        # 보유종목 정리
        hold_lines = []
        total_held = 0
        for code, h in holdings.items():
            name = STOCK_NAMES.get(code, code)
            val = h["현재가"] * h["잔고수량"]
            total_held += val
            trend = trends.get(code, "미확인")
            hold_lines.append(
                f"  {name}({code}): {h['잔고수량']}주 평단{h['매입단가']:,} "
                f"현재{h['현재가']:,} 수익률{h['수익률']:+.1f}% 추세:{trend}"
            )
        cash = total_asset - total_held

        # 시세 정리
        price_lines = []
        for code, p in prices.items():
            if p.get("현재가", 0) == 0:
                continue
            name = STOCK_NAMES.get(code, code)
            held = "★" if code in holdings else " "
            price_lines.append(
                f" {held}{name}({code}): {p['현재가']:,}원 ({p.get('등락률',0):+.2f}%) "
                f"거래량:{p.get('거래량',0):,}"
            )

        # 뉴스 정리
        news_lines = [f"  - {n['title']}" for n in news[:10]]

        # 야간 플랜
        plan_text = ""
        if self._overnight_plan:
            plan_text = f"\n## 야간 분석 결과\n{self._overnight_plan.get('summary', '없음')}"

        prompt = f"""당신은 한국 주식 스윙 트레이딩 AI입니다.
목표: {self.config['target_date']}(금) 장 마감 시 평가액 극대화 (D-{days_left})

## 현재 포트폴리오
추정순자산: {total_asset:,}원 | 추정손익: {total_pnl:,}원 | 현금: {cash:,}원
{chr(10).join(hold_lines) if hold_lines else '  보유 없음'}

## 전 종목 시세
{chr(10).join(price_lines)}

## 최근 뉴스/공시
{chr(10).join(news_lines) if news_lines else '  최근 뉴스 없음'}
{plan_text}

## 매매 규칙
- 스윙 트레이딩: 매도 후 재매수도 가능 (단, 비용 고려)
- 매수 수수료 0.015%, 매도 수수료 0.015% + 거래세 0.18%
- 종목당 최대 비중 {self.config['max_position_pct']}%
- 하루 최대 거래 {self.config['daily_max_trades']}건 (현재 {self._daily_trade_count}건)
- D-{days_left}: {'적극적' if days_left <= 1 else '신중한'} 포지셔닝

## 판단 기준
1. 뉴스/공시에서 호재/악재 파악
2. 모멘텀 + 수급 분석 (거래량, 등락률)
3. 섹터 로테이션 가능성
4. 금요일까지의 상승 여력
5. 비용 대비 수익 기대값

## 응답 (JSON만 출력)
{{"actions": [
  {{"action": "buy|sell", "code": "종목코드", "qty": 수량, "reason": "근거"}}
], "analysis": "시장 분석 한줄", "confidence": "high|medium|low"}}
행동 없으면: {{"actions": [], "analysis": "관망 근거", "confidence": "high"}}"""

        try:
            resp = await self.ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            decision = json.loads(text)
            actions = []
            for a in decision.get("actions", []):
                code = a.get("code", "")
                qty = int(a.get("qty", 0))
                action = a.get("action", "")
                if not code or qty <= 0 or action not in ("buy", "sell"):
                    continue

                # 매수 검증
                if action == "buy":
                    price = prices.get(code, {}).get("현재가", 0)
                    if price <= 0:
                        continue
                    amount = price * qty
                    max_per_stock = total_asset * self.config["max_position_pct"] / 100
                    existing = holdings.get(code, {})
                    existing_val = existing.get("현재가", 0) * existing.get("잔고수량", 0) if existing else 0
                    if amount + existing_val > max_per_stock:
                        continue
                    if amount > cash:
                        qty = int(cash * 0.95 / price)
                        if qty <= 0:
                            continue

                # 매도 검증
                if action == "sell":
                    held = holdings.get(code, {}).get("잔고수량", 0)
                    if held <= 0:
                        continue
                    qty = min(qty, held)

                actions.append({
                    "action": action,
                    "code": code,
                    "qty": qty,
                    "reason": a.get("reason", "AI 판단"),
                })

            return actions

        except json.JSONDecodeError as e:
            logger.warning(f"[swing] AI 응답 파싱 실패: {e}")
            return []
        except Exception as e:
            logger.error(f"[swing] AI 판단 오류: {e}")
            return []

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        dtype = decision.get("type", "")

        if dtype == "trade":
            await self._execute_trades(decision.get("actions", []))
        elif dtype == "hourly_report":
            await self._send_hourly_report(decision.get("ctx", {}))
        elif dtype == "pre_market":
            await self._execute_pre_market(decision.get("plan", {}))
        elif dtype == "overnight_analysis":
            await self._analyze_overnight(decision)

    async def _execute_trades(self, actions: list[dict]):
        """매매 주문 실행 (장중에만)"""
        if not self.ls or not self.ls.is_configured:
            return

        # 장중이 아니면 매매 금지 (모의투자 장외 체결 버그 방지)
        if not self._is_market_hours():
            logger.warning("[swing] 장외 시간 매매 시도 차단")
            return

        for action in actions:
            code = action["code"]
            qty = action["qty"]
            name = STOCK_NAMES.get(code, code)
            reason = action.get("reason", "")

            try:
                if action["action"] == "buy":
                    result = await self.ls.buy(code, qty)
                    emoji, action_str = "📈", "매수"
                elif action["action"] == "sell":
                    result = await self.ls.sell(code, qty)
                    emoji, action_str = "📉", "매도"
                else:
                    continue

                success = result.get("결과") == "성공"
                order_no = result.get("주문번호", "")

                if success:
                    self._daily_trade_count += 1

                self._trade_log.append({
                    "time": self._now().isoformat(),
                    "action": action_str,
                    "code": code, "name": name,
                    "qty": qty, "success": success,
                    "order_no": order_no, "reason": reason,
                })

                # Supabase 기록
                try:
                    self.supabase.table("auto_trade_log").insert({
                        "trade_time": self._now().isoformat(),
                        "action": action_str,
                        "stock_code": code,
                        "stock_name": name,
                        "quantity": qty,
                        "success": success,
                        "order_no": order_no,
                        "reason": f"[스윙] {reason}",
                    }).execute()
                except Exception as e:
                    logger.warning(f"[swing] DB 기록 실패: {e}")

                # 슬랙 보고
                if success:
                    msg = (
                        f"{emoji} *[스윙트레이딩] {action_str} 완료*\n"
                        f"{name}({code}) | {qty}주 | 주문#{order_no}\n"
                        f"사유: {reason}"
                    )
                else:
                    msg = (
                        f"❌ *[스윙트레이딩] {action_str} 실패*\n"
                        f"{name}({code}) | {qty}주\n"
                        f"에러: {result.get('에러', '알 수 없음')}"
                    )
                await self.say(msg, self.CHANNEL)

            except Exception as e:
                logger.error(f"[swing] 주문 오류 {code}: {e}")
                await self.log(f"❌ 주문 오류: {name}({code}) {e}")

    async def _send_hourly_report(self, ctx: dict):
        """매시간 포트폴리오 현황 보고"""
        balance = ctx.get("balance", {})
        holdings = ctx.get("holdings", {})
        prices = ctx.get("prices", {})
        days_left = ctx.get("days_to_target", 99)

        summary = balance.get("summary", {})
        total_asset = summary.get("추정순자산", 0)
        total_pnl = summary.get("추정손익", 0)

        now = self._now()
        lines = [
            f"📊 *[스윙트레이딩] {now.strftime('%H:%M')} 현황* (D-{days_left})",
            f"추정순자산: {total_asset:,}원 | 손익: {total_pnl:,}원",
            "",
        ]

        for code, h in holdings.items():
            name = STOCK_NAMES.get(code, code)
            val = h["현재가"] * h["잔고수량"]
            pct = val / total_asset * 100 if total_asset else 0
            lines.append(
                f"  {name}: {h['잔고수량']}주 {h['현재가']:,}원 "
                f"({h['수익률']:+.1f}%) [{pct:.0f}%]"
            )

        # 오늘 거래 내역
        today_trades = [t for t in self._trade_log if t["time"].startswith(self._last_date)]
        if today_trades:
            lines.append(f"\n오늘 거래: {len(today_trades)}건")
            for t in today_trades[-5:]:
                s = "✅" if t["success"] else "❌"
                lines.append(f"  {s} {t['action']} {t['name']} {t['qty']}주")

        await self.say("\n".join(lines), self.CHANNEL)

    async def _execute_pre_market(self, plan: dict):
        """장 오픈 전 분석 보고 (매매는 _execute_trades의 장중 체크가 보호)"""
        summary = plan.get("summary", "")
        trades = plan.get("trades", [])

        msg = f"🌅 *[프리마켓 분석]* D-{self._days_to_target()}\n{summary}"
        if trades:
            msg += "\n\n장 오픈 시 실행 예정:"
            for t in trades:
                msg += f"\n  → {t.get('action','')} {STOCK_NAMES.get(t.get('code',''), t.get('code',''))} {t.get('qty','')}주: {t.get('reason','')}"

        await self.say(msg, self.CHANNEL)

    async def _analyze_overnight(self, decision: dict):
        """장외 뉴스 분석 + 전략 수립"""
        items = decision.get("items", [])
        if not items:
            return

        news_text = "\n".join(f"- {i['title']}" for i in items[:20])

        # 보유 현황 정리
        hold_text = ""
        if self._holdings:
            lines = []
            for code, h in self._holdings.items():
                name = STOCK_NAMES.get(code, code)
                lines.append(f"  {name}({code}): {h['잔고수량']}주 수익률:{h['수익률']:+.1f}%")
            hold_text = f"\n## 현재 보유\n{chr(10).join(lines)}"

        prompt = f"""장외 시간 뉴스 분석 및 내일 전략을 수립하세요.

## 최근 뉴스/공시
{news_text}
{hold_text}

## 분석 요청
1. 각 뉴스가 보유종목/관심종목에 미치는 영향 분석
2. 내일 시장 전망 (호재/악재 정리)
3. 내일 장 오픈 시 대응 전략 (매수/매도/관망)
4. 구체적인 거래 계획 (있다면)

## 응답 (JSON)
{{"summary": "전체 분석 요약 (2-3줄)",
  "impact": [{{"news": "뉴스제목", "effect": "긍정/부정/중립", "stocks": ["코드"], "detail": "영향설명"}}],
  "tomorrow_outlook": "내일 전망",
  "trades": [{{"action": "buy|sell", "code": "종목코드", "qty": 수량, "reason": "근거"}}]
}}"""

        try:
            resp = await self.ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            analysis = json.loads(text)
            self._overnight_plan = analysis
            self._overnight_plan["executed"] = False

            # 슬랙 보고
            impact_emoji = {"긍정": "🟢", "부정": "🔴", "중립": "⚪"}
            lines = [
                f"🌙 *[야간 뉴스 분석]* D-{self._days_to_target()}",
                f"_{analysis.get('summary', '')}_",
                "",
            ]
            for imp in analysis.get("impact", [])[:5]:
                e = impact_emoji.get(imp.get("effect", "중립"), "⚪")
                stocks = ", ".join(STOCK_NAMES.get(s, s) for s in imp.get("stocks", []))
                lines.append(f"{e} {imp.get('detail', imp.get('news', ''))} [{stocks}]")

            if analysis.get("tomorrow_outlook"):
                lines.append(f"\n📋 내일 전망: {analysis['tomorrow_outlook']}")

            if analysis.get("trades"):
                lines.append("\n🎯 계획된 거래:")
                for t in analysis["trades"]:
                    name = STOCK_NAMES.get(t.get("code", ""), t.get("code", ""))
                    lines.append(f"  → {t.get('action','')} {name} {t.get('qty','')}주: {t.get('reason','')}")

            await self.say("\n".join(lines), self.CHANNEL)

            # Supabase 저장
            try:
                self.supabase.table("collected_items").insert({
                    "hash": f"overnight_{self._now().strftime('%Y%m%d_%H')}",
                    "title": f"[야간분석] {analysis.get('summary', '')[:100]}",
                    "content": json.dumps(analysis, ensure_ascii=False),
                    "source": "swing_trader",
                    "source_type": "analysis",
                }).execute()
            except Exception as e:
                logger.warning(f"[swing] 분석 저장 실패: {e}")

        except json.JSONDecodeError:
            logger.warning("[swing] 야간 분석 JSON 파싱 실패")
        except Exception as e:
            logger.error(f"[swing] 야간 분석 오류: {e}")

    # ── 정리 ───────────────────────────────────────────

    async def cleanup(self):
        await self._http.aclose()
