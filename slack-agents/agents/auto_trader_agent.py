"""
자율 거래 에이전트 - AI 기반 데이트레이딩

BaseAgent를 상속하여 orchestrator에 통합.
매 사이클: 시세 수집 → AI 매매 판단 → 주문 실행 → 결과 기록

전략 규칙:
- 장 시간(09:00~15:20)에만 매매
- 3시 15분 이후 신규 매수 금지
- 3시 20분까지 전량 매도
- 보유 금액 한도 준수
- 손절(-0.5%)/익절(+1%) 기계적 실행
- 거래 내역 노션/Supabase 기록
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 기본 설정
DEFAULT_CONFIG = {
    "max_position_amount": 200_000_000,   # 최대 보유 금액 (2억)
    "per_stock_limit": 50_000_000,        # 종목당 최대 (5천만)
    "stop_loss_pct": -1.5,               # 손절선 (-1.5%, 시장가 슬리피지 반영)
    "take_profit_pct": 1.0,              # 익절선 (+1%)
    "half_profit_pct": 0.5,              # 절반 익절선 (+0.5%)
    "max_stocks": 5,                     # 최대 동시 보유 종목 수 (집중 관리)
    "no_buy_after": "15:15",             # 이 시간 이후 매수 금지
    "force_sell_by": "15:20",            # 이 시간까지 전량 매도
    # 시즌4 매매 규칙 엔진
    "min_hold_minutes": 30,              # 최소 보유시간 (분) - 패닉셀 방지
    "max_daily_trades": 6,               # 하루 최대 매매 횟수 (과매매 방지)
    "no_chase_pct": 5.0,                 # 이 등락률 이상 급등주 매수 금지
    "max_same_sector": 2,                # 동일 섹터 최대 종목 수
    "prefer_limit_order": True,          # 지정가 주문 우선 사용
    "spread_threshold_pct": 0.3,         # 이 이상이면 반드시 지정가
    "scan_tickers": [                    # 스캔 대상 종목
        "005930", "000660", "005380", "000270",  # 삼성전자, SK하이닉스, 현대차, 기아
        "006400", "035720", "068270", "003670",  # 삼성SDI, 카카오, 셀트리온, 포스코퓨처엠
        "009150", "105560", "051910", "066570",  # 삼성전기, KB금융, LG화학, LG전자
        "035420", "028260", "012330", "055550",  # NAVER, 삼성물산, 현대모비스, 신한지주
    ],
    "loop_interval": 60,                 # 매매 판단 주기 (초)
}

# 종목코드 → 종목명 매핑
STOCK_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차",
    "000270": "기아", "006400": "삼성SDI", "035720": "카카오",
    "068270": "셀트리온", "003670": "포스코퓨처엠", "009150": "삼성전기",
    "105560": "KB금융", "051910": "LG화학", "066570": "LG전자",
    "035420": "NAVER", "028260": "삼성물산", "012330": "현대모비스",
    "055550": "신한지주", "373220": "LG에너지솔루션", "207940": "삼성바이오로직스",
}

# 섹터 분류 (동일 섹터 과집중 방지용)
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


class AutoTraderAgent(BaseAgent):
    """AI 기반 자율 매매 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, ls_client=None, **kwargs):
        super().__init__(
            name="auto_trader",
            description="AI 기반 자율 데이트레이딩 에이전트",
            loop_interval=int(os.environ.get(
                "AUTO_TRADER_INTERVAL",
                DEFAULT_CONFIG["loop_interval"],
            )),
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self.ls = ls_client
        self.config = dict(DEFAULT_CONFIG)
        # 환경변수로 설정 오버라이드
        if os.environ.get("AUTO_TRADER_MAX_POSITION"):
            self.config["max_position_amount"] = int(os.environ["AUTO_TRADER_MAX_POSITION"])
        if os.environ.get("AUTO_TRADER_TICKERS"):
            self.config["scan_tickers"] = os.environ["AUTO_TRADER_TICKERS"].split(",")

        self._trade_log: list[dict] = []
        self._session_start = None
        self._daily_pnl = 0
        self._cycle = 0
        self._daily_trade_count = 0  # 당일 매매 횟수
        self._last_prices: dict[str, dict] = {}  # 종목코드 → 시세 데이터
        self._holdings: dict[str, dict] = {}      # 종목코드 → 보유 정보
        self._buy_times: dict[str, datetime] = {}  # 종목코드 → 매수 시각
        self._enabled = os.environ.get("AUTO_TRADER_ENABLED", "false").lower() == "true"
        self._reported_today = False

    def _now_kst(self) -> datetime:
        return datetime.now(KST)

    def _is_trading_hours(self) -> bool:
        """정규 장 시간인지 확인"""
        now = self._now_kst()
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close

    def _is_no_buy_time(self) -> bool:
        """매수 금지 시간인지 확인"""
        now = self._now_kst()
        h, m = map(int, self.config["no_buy_after"].split(":"))
        cutoff = now.replace(hour=h, minute=m, second=0)
        return now >= cutoff

    def _is_force_sell_time(self) -> bool:
        """강제 매도 시간인지 확인"""
        now = self._now_kst()
        h, m = map(int, self.config["force_sell_by"].split(":"))
        cutoff = now.replace(hour=h, minute=m, second=0)
        return now >= cutoff

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """시장 데이터 수집"""
        if not self._enabled:
            return None

        if not self.ls or not self.ls.is_configured:
            logger.warning("[auto_trader] LS증권 클라이언트 미설정")
            return None

        if not self._is_trading_hours():
            # 장 마감 후 일일 보고서
            if self._trade_log and not self._reported_today:
                await self._send_daily_report()
                self._reported_today = True
            return None

        self._reported_today = False
        if not self._session_start:
            self._session_start = self._now_kst()
            await self.log("🤖 자율 거래 에이전트 가동 시작")

        self._cycle += 1

        # 1) 잔고 조회
        balance = await self.ls.get_balance()
        holdings = {}
        for h in balance.get("holdings", []):
            if h["잔고수량"] > 0:
                holdings[h["종목코드"]] = h
        self._holdings = holdings

        # 2) 시세 수집 (보유 종목 + 스캔 대상)
        tickers = set(self.config["scan_tickers"])
        tickers.update(holdings.keys())

        prices = {}
        for code in tickers:
            try:
                p = await self.ls.get_price(code)
                if not p.get("unavailable"):
                    prices[code] = p
                    self._last_prices[code] = p
            except Exception as e:
                logger.warning(f"[auto_trader] 시세 조회 실패 {code}: {e}")

        # 3) 뉴스/공시 데이터 (Supabase에서 최근 수집 정보)
        market_news = []
        try:
            resp = self.supabase.table("collected_items").select(
                "title,source,content"
            ).order(
                "created_at", desc=True
            ).limit(10).execute()
            market_news = resp.data or []
        except Exception as e:
            logger.warning(f"[auto_trader] 뉴스 조회 실패: {e}")

        return {
            "cycle": self._cycle,
            "balance": balance,
            "holdings": holdings,
            "prices": prices,
            "news": market_news,
            "is_force_sell": self._is_force_sell_time(),
            "is_no_buy": self._is_no_buy_time(),
        }

    # ── Think ──────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """AI로 매매 판단"""
        actions = []

        # 1) 강제 매도 시간: 보유 종목 전량 매도
        if context["is_force_sell"]:
            for code, h in context["holdings"].items():
                if h["잔고수량"] > 0:
                    actions.append({
                        "action": "sell",
                        "code": code,
                        "qty": h["잔고수량"],
                        "reason": "장마감 전 강제 매도",
                    })
            if actions:
                return {"actions": actions, "reasoning": "장마감 전 전량 매도"}
            return None

        # 2) 기계적 손절/익절 체크 (최소 보유시간 규칙 적용)
        now = self._now_kst()
        min_hold = self.config.get("min_hold_minutes", 30)

        for code, h in context["holdings"].items():
            if h["잔고수량"] <= 0:
                continue
            pnl_pct = h["수익률"]
            buy_time = self._buy_times.get(code)
            held_minutes = (now - buy_time).total_seconds() / 60 if buy_time else 999

            # 손절 (긴급 손절은 보유시간 무관, 일반 손절은 최소 보유시간 적용)
            if pnl_pct <= self.config["stop_loss_pct"]:
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": h["잔고수량"],
                    "reason": f"손절: {pnl_pct:.1f}% (보유 {held_minutes:.0f}분)",
                })
            # 최소 보유시간 미만이면 익절 보류 (패닉셀 방지)
            elif held_minutes < min_hold:
                continue
            # 익절 (전량)
            elif pnl_pct >= self.config["take_profit_pct"]:
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": h["잔고수량"],
                    "reason": f"익절: {pnl_pct:.1f}% (보유 {held_minutes:.0f}분)",
                })
            # 절반 익절
            elif pnl_pct >= self.config["half_profit_pct"]:
                half = max(1, h["잔고수량"] // 2)
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": half,
                    "reason": f"절반 익절: {pnl_pct:.1f}% (보유 {held_minutes:.0f}분)",
                })

        # 3) 매수 금지 시간이면 매도만 실행
        if context["is_no_buy"] and actions:
            return {"actions": actions, "reasoning": "매수 금지 시간, 손절/익절만 실행"}

        if context["is_no_buy"]:
            return None

        # 4) AI 매매 판단 (매수 기회 탐색)
        try:
            ai_decision = await self._ai_decide(context)
            if ai_decision:
                actions.extend(ai_decision)
        except Exception as e:
            logger.error(f"[auto_trader] AI 판단 오류: {e}")

        if not actions:
            return None

        return {"actions": actions, "reasoning": "AI 매매 판단"}

    async def _ai_decide(self, context: dict) -> list[dict]:
        """Claude AI로 매수 종목 판단 (매매 규칙 엔진 적용)"""
        # 매매 횟수 제한 체크
        max_trades = self.config.get("max_daily_trades", 6)
        if self._daily_trade_count >= max_trades:
            logger.info(f"[auto_trader] 일일 매매 한도 도달 ({self._daily_trade_count}/{max_trades})")
            return []

        # 보유 종목 수 제한 체크
        current_holding_count = len([
            h for h in context["holdings"].values() if h["잔고수량"] > 0
        ])
        if current_holding_count >= self.config["max_stocks"]:
            return []

        # 현재 보유 금액 계산
        total_position = sum(
            h["현재가"] * h["잔고수량"]
            for h in context["holdings"].values()
            if h["잔고수량"] > 0
        )
        remaining_budget = self.config["max_position_amount"] - total_position

        if remaining_budget < 1_000_000:
            return []

        # 보유 종목의 섹터 카운트
        held_sectors: dict[str, int] = {}
        for code in context["holdings"]:
            sector = STOCK_SECTORS.get(code, "기타")
            held_sectors[sector] = held_sectors.get(sector, 0) + 1

        # 급등주 필터링 & 시세 데이터 정리
        no_chase_pct = self.config.get("no_chase_pct", 5.0)
        price_summary = []
        eligible_codes = set()
        for code, p in context["prices"].items():
            if p.get("현재가", 0) == 0:
                continue
            name = STOCK_NAMES.get(code, code)
            change_pct = p.get("등락률", 0)

            # 호가 스프레드 분석
            spread_info = ""
            if self.ls and hasattr(self.ls, "analyze_spread"):
                spread = self.ls.analyze_spread(p)
                spread_pct = spread.get("스프레드비율", 0)
                spread_info = f" 스프레드:{spread_pct:.2f}%({spread.get('추천주문방식', '')})"

            price_summary.append(
                f"{name}({code}): {p['현재가']:,}원 ({change_pct:+.2f}%) 거래량:{p.get('거래량', 0):,}{spread_info}"
            )

            # 매수 자격 체크: 급등주 제외, 보유종목 제외, 섹터 제한
            if code in context["holdings"]:
                continue
            if abs(change_pct) > no_chase_pct:
                continue
            sector = STOCK_SECTORS.get(code, "기타")
            max_sector = self.config.get("max_same_sector", 2)
            if held_sectors.get(sector, 0) >= max_sector:
                continue
            eligible_codes.add(code)

        # 보유 종목 정리
        holding_summary = []
        for code, h in context["holdings"].items():
            if h["잔고수량"] > 0:
                name = STOCK_NAMES.get(code, code)
                holding_summary.append(
                    f"{name}({code}): {h['잔고수량']}주, 수익률:{h['수익률']:.1f}%"
                )

        # 분봉 추세 데이터 수집 (매수 가능 종목만)
        trend_summary = []
        if self.ls and hasattr(self.ls, "get_minute_bars"):
            for code in list(eligible_codes)[:6]:  # 상위 6종목만
                try:
                    bars = await self.ls.get_minute_bars(code, interval=5, count=20)
                    if bars:
                        trend = self.ls.detect_trend(bars)
                        name = STOCK_NAMES.get(code, code)
                        trend_summary.append(f"{name}({code}): 5분봉 추세={trend}")
                except Exception as e:
                    logger.warning(f"[auto_trader] 분봉 조회 실패 {code}: {e}")

        # 뉴스 요약
        news_summary = "\n".join(
            f"- {n['title']}" for n in context["news"][:5]
        ) if context["news"] else "최근 뉴스 없음"

        trend_text = "\n".join(trend_summary) if trend_summary else "분봉 데이터 없음"

        prompt = f"""당신은 한국 주식 데이트레이딩 AI입니다. 현재 시장 데이터를 분석하고 매수할 종목을 추천하세요.

## 현재 시세 (호가 스프레드 포함)
{chr(10).join(price_summary)}

## 분봉 추세 분석
{trend_text}

## 보유 종목
{chr(10).join(holding_summary) if holding_summary else "없음"}

## 남은 매수 가능 금액
{remaining_budget:,}원

## 최근 뉴스
{news_summary}

## 매매 규칙 (반드시 준수)
- 등락률 +2%~+5% 구간의 초기 모멘텀 종목 선호
- +{no_chase_pct}% 이상 급등주 매수 금지
- 5분봉 추세가 "상승"인 종목만 매수 (데이터 있을 경우)
- 거래량 활발한 종목 우선
- 종목당 최대 {self.config['per_stock_limit']:,}원
- 현재 보유 종목 추가 매수 금지
- 매수 가능 종목: {', '.join(eligible_codes) if eligible_codes else '없음'}
- 스프레드 > 0.3%이면 지정가 주문 사용
- 수수료(0.015%)+증권거래세(0.18%) 고려하여 최소 +0.5% 이상 수익 기대 종목만

## 응답 형식 (JSON)
매수할 종목이 있으면:
{{"buy": [{{"code": "종목코드", "qty": 주문수량, "limit_price": 지정가(0이면시장가), "reason": "매수 근거"}}]}}
매수할 종목이 없으면:
{{"buy": [], "reason": "관망 근거"}}

반드시 유효한 JSON만 출력하세요."""

        resp = await self.ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = resp.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[auto_trader] AI 응답 JSON 파싱 실패: {text[:200]}")
            return []

        actions = []
        for buy in decision.get("buy", []):
            code = buy.get("code", "")
            qty = int(buy.get("qty", 0))
            if code and qty > 0 and code in eligible_codes:
                price = context["prices"].get(code, {}).get("현재가", 0)
                if price > 0:
                    order_amount = price * qty
                    if order_amount <= min(remaining_budget, self.config["per_stock_limit"]):
                        limit_price = int(buy.get("limit_price", 0))
                        actions.append({
                            "action": "buy",
                            "code": code,
                            "qty": qty,
                            "limit_price": limit_price,
                            "reason": buy.get("reason", "AI 판단"),
                        })
                        remaining_budget -= order_amount

        return actions

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        """매매 주문 실행 (지정가/시장가 자동 결정, 비용 기록)"""
        from integrations.ls_securities import LSSecuritiesClient

        actions = decision.get("actions", [])
        if not actions:
            return

        for action in actions:
            code = action["code"]
            qty = action["qty"]
            name = STOCK_NAMES.get(code, code)
            reason = action.get("reason", "")
            limit_price = action.get("limit_price", 0)

            try:
                if action["action"] == "buy":
                    # 지정가 주문 여부 결정
                    if limit_price and self.config.get("prefer_limit_order"):
                        result = await self.ls.buy_limit(code, qty, limit_price)
                        order_type = f"지정가({limit_price:,}원)"
                    else:
                        # 호가 스프레드 체크 → 자동 결정
                        price_data = self._last_prices.get(code, {})
                        spread = self.ls.analyze_spread(price_data)
                        threshold = self.config.get("spread_threshold_pct", 0.3)
                        if spread.get("스프레드비율", 0) > threshold and spread.get("매수추천가"):
                            result = await self.ls.buy_limit(code, qty, spread["매수추천가"])
                            order_type = f"지정가({spread['매수추천가']:,}원, 스프레드{spread['스프레드비율']:.2f}%)"
                        else:
                            result = await self.ls.buy(code, qty)
                            order_type = "시장가"
                    emoji = "📈"
                    action_str = "매수"
                elif action["action"] == "sell":
                    if limit_price and self.config.get("prefer_limit_order"):
                        result = await self.ls.sell_limit(code, qty, limit_price)
                        order_type = f"지정가({limit_price:,}원)"
                    else:
                        result = await self.ls.sell(code, qty)
                        order_type = "시장가"
                    emoji = "📉"
                    action_str = "매도"
                else:
                    continue

                success = result.get("결과") == "성공"
                order_no = result.get("주문번호", "")

                # 매수 시각 기록 (보유시간 추적용)
                if success and action_str == "매수":
                    self._buy_times[code] = self._now_kst()

                # 매매 횟수 카운트
                if success:
                    self._daily_trade_count += 1

                # 매매 비용 계산
                price_now = self._last_prices.get(code, {}).get("현재가", 0)
                cost = LSSecuritiesClient.estimate_trading_cost(
                    price_now or limit_price, qty,
                    side="buy" if action_str == "매수" else "sell"
                )

                # 거래 로그 기록
                log_entry = {
                    "time": self._now_kst().isoformat(),
                    "action": action_str,
                    "code": code,
                    "name": name,
                    "qty": qty,
                    "success": success,
                    "order_no": order_no,
                    "order_type": order_type,
                    "reason": reason,
                    "error": result.get("에러", ""),
                    "estimated_cost": cost,
                }
                self._trade_log.append(log_entry)

                # Supabase 기록 (비용 포함)
                try:
                    self.supabase.table("auto_trade_log").insert({
                        "trade_time": self._now_kst().isoformat(),
                        "action": action_str,
                        "stock_code": code,
                        "stock_name": name,
                        "quantity": qty,
                        "success": success,
                        "order_no": order_no,
                        "reason": f"{reason} | {order_type} | 비용:{cost['총비용']:,}원",
                        "error_msg": result.get("에러", ""),
                    }).execute()
                except Exception as e:
                    logger.warning(f"[auto_trader] DB 기록 실패: {e}")

                # 슬랙 보고
                if success:
                    cost_info = f"수수료:{cost['수수료']:,}원"
                    if cost['증권거래세']:
                        cost_info += f"+세금:{cost['증권거래세']:,}원"
                    msg = (
                        f"{emoji} *[자율거래] {action_str} 완료*\n"
                        f"{name}({code}) | {qty}주 | {order_type} | 주문번호: {order_no}\n"
                        f"사유: {reason}\n"
                        f"예상비용: {cost_info} (총 {cost['총비용']:,}원)"
                    )
                else:
                    msg = f"❌ *[자율거래] {action_str} 실패*\n{name}({code}) | {qty}주\n에러: {result.get('에러', '알 수 없음')}"

                await self.log(msg)

            except Exception as e:
                logger.error(f"[auto_trader] 주문 실행 오류 {code}: {e}")
                await self.log(f"❌ 주문 실행 오류: {name}({code}) {e}")

    # ── 일일 보고서 ─────────────────────────────────────

    async def _send_daily_report(self):
        """장 마감 후 일일 거래 보고서 전송"""
        if not self._trade_log:
            return

        today = self._now_kst().strftime("%Y-%m-%d")
        total_trades = len(self._trade_log)
        buys = [t for t in self._trade_log if t["action"] == "매수"]
        sells = [t for t in self._trade_log if t["action"] == "매도"]
        errors = [t for t in self._trade_log if not t["success"]]

        # 잔고 조회
        balance = await self.ls.get_balance()
        pnl = balance.get("summary", {}).get("추정손익", 0)
        total_asset = balance.get("summary", {}).get("추정순자산", 0)

        report = f"""📊 *[자율거래] {today} 일일 보고서*

*거래 요약*
- 총 거래: {total_trades}건 (매수 {len(buys)}건, 매도 {len(sells)}건)
- 에러: {len(errors)}건
- 추정순자산: {total_asset:,}원
- 추정손익: {pnl:,}원

*거래 내역*"""

        for t in self._trade_log[-20:]:  # 최근 20건
            status = "✅" if t["success"] else "❌"
            report += f"\n{status} {t['time'][11:19]} {t['action']} {t['name']}({t['code']}) {t['qty']}주 - {t['reason']}"

        await self.log(report)

        # 노션 저장 (AI 에이전트 결과물 DB)
        try:
            notion_db_id = os.environ.get(
                "NOTION_AGENT_RESULTS_DB_ID",
                "1e21114e-6491-8101-8b67-ca52d78a8fb0",
            )
            if self.notion:
                from integrations.notion_client import NotionClient
                await self.notion.create_page(
                    database_id=notion_db_id,
                    properties={
                        "이름": NotionClient.prop_title(
                            f"[자율거래] {today} 일일 보고서"
                        ),
                    },
                    content_blocks=[
                        NotionClient.block_heading(f"{today} 자율 거래 보고서"),
                        NotionClient.block_paragraph(
                            f"총 거래: {total_trades}건 | 추정손익: {pnl:,}원 | 추정순자산: {total_asset:,}원"
                        ),
                        NotionClient.block_divider(),
                        NotionClient.block_heading("거래 내역", level=3),
                    ] + [
                        NotionClient.block_paragraph(
                            f"{'✅' if t['success'] else '❌'} {t['time'][11:19]} {t['action']} {t['name']} {t['qty']}주 - {t['reason']}"
                        )
                        for t in self._trade_log
                    ],
                )
                logger.info("[auto_trader] 일일 보고서 노션 저장 완료")
        except Exception as e:
            logger.warning(f"[auto_trader] 노션 저장 실패: {e}")

        # 다음날을 위해 로그 초기화
        self._trade_log = []
        self._session_start = None
        self._cycle = 0
