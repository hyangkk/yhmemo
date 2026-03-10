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
    "stop_loss_pct": -0.5,               # 손절선 (-0.5%)
    "take_profit_pct": 1.0,              # 익절선 (+1%)
    "half_profit_pct": 0.5,              # 절반 익절선 (+0.5%)
    "max_stocks": 8,                     # 최대 동시 보유 종목 수
    "no_buy_after": "15:15",             # 이 시간 이후 매수 금지
    "force_sell_by": "15:20",            # 이 시간까지 전량 매도
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
        self._last_prices: dict[str, dict] = {}  # 종목코드 → 시세 데이터
        self._holdings: dict[str, dict] = {}      # 종목코드 → 보유 정보
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

        # 2) 기계적 손절/익절 체크
        for code, h in context["holdings"].items():
            if h["잔고수량"] <= 0:
                continue
            pnl_pct = h["수익률"]
            # 손절
            if pnl_pct <= self.config["stop_loss_pct"]:
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": h["잔고수량"],
                    "reason": f"손절: {pnl_pct:.1f}%",
                })
            # 익절 (전량)
            elif pnl_pct >= self.config["take_profit_pct"]:
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": h["잔고수량"],
                    "reason": f"익절: {pnl_pct:.1f}%",
                })
            # 절반 익절
            elif pnl_pct >= self.config["half_profit_pct"]:
                half = max(1, h["잔고수량"] // 2)
                actions.append({
                    "action": "sell",
                    "code": code,
                    "qty": half,
                    "reason": f"절반 익절: {pnl_pct:.1f}%",
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
        """Claude AI로 매수 종목 판단"""
        # 현재 보유 금액 계산
        total_position = sum(
            h["현재가"] * h["잔고수량"]
            for h in context["holdings"].values()
            if h["잔고수량"] > 0
        )
        remaining_budget = self.config["max_position_amount"] - total_position

        if remaining_budget < 1_000_000:  # 100만원 미만이면 매수 불가
            return []

        # 시세 데이터 정리
        price_summary = []
        for code, p in context["prices"].items():
            if p.get("현재가", 0) == 0:
                continue
            name = STOCK_NAMES.get(code, code)
            change_pct = p.get("등락률", 0)
            price_summary.append(
                f"{name}({code}): {p['현재가']:,}원 ({change_pct:+.2f}%) 거래량:{p.get('거래량', 0):,}"
            )

        # 보유 종목 정리
        holding_summary = []
        for code, h in context["holdings"].items():
            if h["잔고수량"] > 0:
                name = STOCK_NAMES.get(code, code)
                holding_summary.append(
                    f"{name}({code}): {h['잔고수량']}주, 수익률:{h['수익률']:.1f}%"
                )

        # 뉴스 요약
        news_summary = "\n".join(
            f"- {n['title']}" for n in context["news"][:5]
        ) if context["news"] else "최근 뉴스 없음"

        prompt = f"""당신은 한국 주식 데이트레이딩 AI입니다. 현재 시장 데이터를 분석하고 매수할 종목을 추천하세요.

## 현재 시세
{chr(10).join(price_summary)}

## 보유 종목
{chr(10).join(holding_summary) if holding_summary else "없음"}

## 남은 매수 가능 금액
{remaining_budget:,}원

## 최근 뉴스
{news_summary}

## 매매 규칙
- 등락률 +2%~+5% 구간의 초기 모멘텀 종목 선호
- 이미 +10% 이상 급등한 종목은 회피 (고점 추격 금지)
- 거래량이 활발한 종목 우선
- 종목당 최대 {self.config['per_stock_limit']:,}원
- 현재 보유 종목은 추가 매수 금지

## 응답 형식 (JSON)
매수할 종목이 있으면:
{{"buy": [{{"code": "종목코드", "qty": 주문수량, "reason": "매수 근거"}}]}}
매수할 종목이 없으면:
{{"buy": [], "reason": "관망 근거"}}

반드시 유효한 JSON만 출력하세요."""

        resp = await self.ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        text = resp.content[0].text.strip()
        # JSON 파싱
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
            if code and qty > 0 and code not in context["holdings"]:
                # 금액 한도 체크
                price = context["prices"].get(code, {}).get("현재가", 0)
                if price > 0:
                    order_amount = price * qty
                    if order_amount <= min(remaining_budget, self.config["per_stock_limit"]):
                        actions.append({
                            "action": "buy",
                            "code": code,
                            "qty": qty,
                            "reason": buy.get("reason", "AI 판단"),
                        })
                        remaining_budget -= order_amount

        return actions

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        """매매 주문 실행"""
        actions = decision.get("actions", [])
        if not actions:
            return

        for action in actions:
            code = action["code"]
            qty = action["qty"]
            name = STOCK_NAMES.get(code, code)
            reason = action.get("reason", "")

            try:
                if action["action"] == "buy":
                    result = await self.ls.buy(code, qty)
                    emoji = "📈"
                    action_str = "매수"
                elif action["action"] == "sell":
                    result = await self.ls.sell(code, qty)
                    emoji = "📉"
                    action_str = "매도"
                else:
                    continue

                success = result.get("결과") == "성공"
                order_no = result.get("주문번호", "")

                # 거래 로그 기록
                log_entry = {
                    "time": self._now_kst().isoformat(),
                    "action": action_str,
                    "code": code,
                    "name": name,
                    "qty": qty,
                    "success": success,
                    "order_no": order_no,
                    "reason": reason,
                    "error": result.get("에러", ""),
                }
                self._trade_log.append(log_entry)

                # Supabase 기록
                try:
                    self.supabase.table("auto_trade_log").insert({
                        "trade_time": self._now_kst().isoformat(),
                        "action": action_str,
                        "stock_code": code,
                        "stock_name": name,
                        "quantity": qty,
                        "success": success,
                        "order_no": order_no,
                        "reason": reason,
                        "error_msg": result.get("에러", ""),
                    }).execute()
                except Exception as e:
                    logger.warning(f"[auto_trader] DB 기록 실패: {e}")

                # 슬랙 보고
                if success:
                    msg = f"{emoji} *[자율거래] {action_str} 완료*\n{name}({code}) | {qty}주 | 주문번호: {order_no}\n사유: {reason}"
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
