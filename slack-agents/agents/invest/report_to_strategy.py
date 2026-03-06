"""리포트 텍스트 → 액셔너블 매매전략 변환 모듈

투자 리포트의 자연어 전략 제안을 구조화된 매매전략 JSON으로 변환한다.
AI가 종목코드, 매매방향, 진입/청산 조건, 비중을 추출.
"""

import json
import logging
from dataclasses import dataclass, asdict

import anthropic

logger = logging.getLogger(__name__)

# 한국 주요 종목 매핑 (AI가 종목명→코드 변환할 때 참조)
KR_STOCK_MAP = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "한미반도체": "042700.KS",
    "대한항공": "003490.KS",
    "제주항공": "089590.KS",
    "S-Oil": "010950.KS",
    "에스오일": "010950.KS",
    "롯데케미칼": "011170.KS",
    "LG에너지솔루션": "373220.KS",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "NAVER": "035420.KS",
    "네이버": "035420.KS",
    "카카오": "035720.KS",
    "셀트리온": "068270.KS",
    "POSCO홀딩스": "005490.KS",
    "포스코홀딩스": "005490.KS",
    "KB금융": "105560.KS",
    "신한지주": "055550.KS",
    "하나금융지주": "086790.KS",
    "삼성SDI": "006400.KS",
    "LG화학": "051910.KS",
    "현대모비스": "012330.KS",
    "삼성바이오로직스": "207940.KS",
    "크래프톤": "259960.KS",
}

# 미국 주요 종목/ETF
US_STOCK_MAP = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "TLT": "TLT",
    "GLD": "GLD",
    "엔비디아": "NVDA",
    "NVIDIA": "NVDA",
    "애플": "AAPL",
    "마이크로소프트": "MSFT",
    "테슬라": "TSLA",
    "아마존": "AMZN",
    "메타": "META",
    "구글": "GOOGL",
    "알파벳": "GOOGL",
    "ASML": "ASML",
    "AMD": "AMD",
    "TIGER 미국나스닥100": "QQQ",
    "TIGER 미국필라델피아반도체나스닥": "SOXX",
}

EXTRACT_SYSTEM_PROMPT = """당신은 투자 전략 리포트를 분석하여 구체적이고 실행 가능한 매매전략을 추출하는 퀀트 애널리스트입니다.

리포트에서 다음을 추출하세요:
1. 구체적 종목/ETF (한국 종목은 .KS 접미사, 미국은 그대로)
2. 매매 방향 (long/short)
3. 진입 조건과 청산 조건
4. 포지션 비중
5. 보유 기간

반드시 아래 JSON 형식으로만 응답하세요. 설명 텍스트 없이 JSON만:

```json
{
  "strategies": [
    {
      "name": "전략명 (한국어, 간결하게)",
      "tickers": ["005930.KS", "000660.KS"],
      "direction": "long",
      "action": "buy",
      "weight": 0.10,
      "entry": {
        "type": "market",
        "condition": "진입 조건 설명"
      },
      "exit": {
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "holding_days": 20,
        "exit_condition": "청산 조건 설명"
      },
      "rationale": "전략 근거 1~2문장",
      "confidence": 0.7,
      "risk_level": "medium"
    }
  ],
  "market_view": {
    "overall_sentiment": "bullish/bearish/neutral",
    "key_risk": "주요 리스크 요인",
    "recommended_cash_ratio": 0.3
  }
}
```

규칙:
- 리포트에서 명시적으로 언급된 종목/ETF만 추출 (추측 금지)
- 한국 종목코드는 반드시 6자리 숫자 + .KS (예: 005930.KS)
- 미국 종목/ETF는 티커 그대로 (예: QQQ, NVDA)
- weight는 전체 포트폴리오 대비 비중 (0.05~0.20)
- stop_loss_pct는 음수, take_profit_pct는 양수
- confidence: 0.0~1.0 (전략 확신도)
- risk_level: low/medium/high
- "관망"인 종목은 direction="hold", action="hold"로 표시
- 실제 매매 가능한 전략만 추출 (모호한 제안 제외)

종목코드 참조:
한국: 삼성전자=005930.KS, SK하이닉스=000660.KS, 한미반도체=042700.KS, 대한항공=003490.KS, 제주항공=089590.KS, S-Oil=010950.KS, 롯데케미칼=011170.KS
미국: SPY, QQQ, NVDA, AAPL, MSFT, TSLA, SOXX, AMZN, META, GOOGL, AMD, ASML"""


@dataclass
class TradingStrategy:
    name: str
    tickers: list[str]
    direction: str  # long/short/hold
    action: str     # buy/sell/hold
    weight: float
    entry_type: str
    entry_condition: str
    stop_loss_pct: float
    take_profit_pct: float
    holding_days: int
    exit_condition: str
    rationale: str
    confidence: float
    risk_level: str


@dataclass
class MarketView:
    overall_sentiment: str
    key_risk: str
    recommended_cash_ratio: float


@dataclass
class StrategyPlan:
    strategies: list[TradingStrategy]
    market_view: MarketView
    raw_json: dict


async def extract_strategies(
    report_text: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> StrategyPlan:
    """리포트 텍스트에서 매매전략을 추출한다.

    Args:
        report_text: 투자 전략 리포트 전문
        api_key: Anthropic API key
        model: 사용할 모델

    Returns:
        StrategyPlan with structured trading strategies
    """
    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=EXTRACT_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"아래 투자 전략 리포트에서 매매전략을 추출해주세요.\n\n{report_text}",
        }],
    )

    result_text = response.content[0].text

    # JSON 추출
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]

    data = json.loads(result_text.strip())

    # 구조화
    strategies = []
    for s in data.get("strategies", []):
        if s.get("action") == "hold":
            continue  # 관망은 백테스트 불필요
        exit_info = s.get("exit", {})
        strategies.append(TradingStrategy(
            name=s["name"],
            tickers=s["tickers"],
            direction=s.get("direction", "long"),
            action=s.get("action", "buy"),
            weight=s.get("weight", 0.10),
            entry_type=s.get("entry", {}).get("type", "market"),
            entry_condition=s.get("entry", {}).get("condition", ""),
            stop_loss_pct=exit_info.get("stop_loss_pct", -0.05),
            take_profit_pct=exit_info.get("take_profit_pct", 0.10),
            holding_days=exit_info.get("holding_days", 20),
            exit_condition=exit_info.get("exit_condition", ""),
            rationale=s.get("rationale", ""),
            confidence=s.get("confidence", 0.5),
            risk_level=s.get("risk_level", "medium"),
        ))

    mv = data.get("market_view", {})
    market_view = MarketView(
        overall_sentiment=mv.get("overall_sentiment", "neutral"),
        key_risk=mv.get("key_risk", ""),
        recommended_cash_ratio=mv.get("recommended_cash_ratio", 0.3),
    )

    return StrategyPlan(
        strategies=strategies,
        market_view=market_view,
        raw_json=data,
    )


def format_strategies_for_slack(plan: StrategyPlan) -> str:
    """매매전략을 슬랙 메시지로 포맷팅"""
    lines = [
        f"*[매매전략 도출 완료]* | 시장 전망: {plan.market_view.overall_sentiment.upper()}",
        f"현금비중 권고: {plan.market_view.recommended_cash_ratio:.0%} | 주요 리스크: {plan.market_view.key_risk}",
        "",
    ]

    for i, s in enumerate(plan.strategies, 1):
        emoji = {"buy": ":chart_with_upwards_trend:", "sell": ":chart_with_downwards_trend:"}.get(s.action, ":bar_chart:")
        risk_emoji = {"low": ":large_green_circle:", "medium": ":large_yellow_circle:", "high": ":red_circle:"}.get(s.risk_level, ":white_circle:")

        lines.append(f"{emoji} *전략 {i}: {s.name}*")
        lines.append(f"   종목: `{'`, `'.join(s.tickers)}`")
        lines.append(f"   방향: *{s.action.upper()}* | 비중: {s.weight:.0%} | 확신도: {s.confidence:.0%} {risk_emoji}")
        lines.append(f"   진입: {s.entry_condition}")
        lines.append(f"   손절: {s.stop_loss_pct:+.1%} | 익절: {s.take_profit_pct:+.1%} | 보유: {s.holding_days}일")
        lines.append(f"   근거: _{s.rationale}_")
        lines.append("")

    return "\n".join(lines)
