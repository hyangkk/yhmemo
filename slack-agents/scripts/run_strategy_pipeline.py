"""투자전략 파이프라인: 리포트 → 매매전략 도출 → 백테스트 → 슬랙 발송

Usage:
    # 샘플 리포트로 실행
    python scripts/run_strategy_pipeline.py

    # 커스텀 리포트 파일로 실행
    python scripts/run_strategy_pipeline.py --report-file path/to/report.txt

    # 백테스트 기간 변경 (기본 1년)
    python scripts/run_strategy_pipeline.py --period 2y

    # 슬랙 발송 없이 터미널 출력만
    python scripts/run_strategy_pipeline.py --no-slack

환경변수:
    ANTHROPIC_API_KEY  - Claude API 키 (필수)
    SLACK_BOT_TOKEN    - 슬랙 봇 토큰 (슬랙 발송 시 필수)
"""

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from agents.invest.report_to_strategy import extract_strategies, format_strategies_for_slack
from agents.invest.strategy_backtester import backtest_plan, format_backtest_for_slack

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SLACK_CHANNEL = "ai-invest"

SAMPLE_REPORT = """*투자 전략 리포트* | 2026-03-06 09:00 오전

*[핵심 뉴스 & 시그널]*

1. *연준 3월 FOMC 동결 전망 강화, 6월 인하 기대 유지*
   - 내용: 파월 의장이 "데이터 의존적 접근"을 재확인. 시장은 6월 25bp 인하를 65% 확률로 반영 중
   - 영향 섹터: 금융, 부동산, 성장주 전반
   - 시장 영향: 중립~긍정

2. *엔비디아 GTC 2026 앞두고 차세대 GPU "Rubin Ultra" 스펙 유출*
   - 내용: HBM4 탑재, 학습 성능 기존 대비 3배. TSMC 3nm 공정 확정.
   - 영향 섹터: AI 반도체, HBM(SK하이닉스/삼성전자)
   - 시장 영향: 긍정

3. *중국 양회 폐막 - GDP 5% 목표, 부양책 기대 이하*
   - 내용: 재정적자율 3.0%, 특별국채 1조위안. 시장 기대 하회.
   - 영향 섹터: 중국 소비재, 원자재, 한국 수출주
   - 시장 영향: 부정

4. *국제유가 WTI $72→$68 급락, OPEC+ 증산 합의*
   - 내용: 사우디 주도로 4월부터 일 50만배럴 증산.
   - 영향 섹터: 정유/화학(부정), 항공/해운(긍정)
   - 시장 영향: 혼조

5. *한국 2월 수출 +8.2% YoY, 반도체 +32% 역대급*
   - 내용: AI 서버용 HBM·DDR5 수출이 견인.
   - 영향 섹터: 반도체(SK하이닉스, 삼성전자)
   - 시장 영향: 긍정

*[투자 전략 제안]*

1. *AI 반도체 비중 확대*
   - 대상: SK하이닉스, 한미반도체, TIGER 미국필라델피아반도체나스닥 ETF
   - 액션: 비중 확대 (현재 비중 대비 +5~10%)
   - 근거: HBM 수출 역대급 + 엔비디아 차세대 GPU 수요 확인
   - 리스크: 엔비디아 GTC에서 예상 하회 시 단기 차익실현

2. *항공주 트레이딩 매수*
   - 대상: 대한항공, 제주항공
   - 액션: 단기 매수 (2~4주 보유)
   - 근거: 유가 $68 하락 + 봄 여행 시즌
   - 리스크: 유가 반등 시 빠르게 청산

3. *정유/화학 비중 축소*
   - 대상: S-Oil, 롯데케미칼
   - 액션: 비중 축소 또는 관망
   - 근거: OPEC+ 증산 + 중국 수요 부진
   - 리스크: 지정학 리스크 재부각 시 유가 급반등

4. *미국 성장주 ETF 분할매수*
   - 대상: QQQ
   - 액션: 3회 분할매수
   - 근거: 6월 금리 인하 기대 유지 + AI 모멘텀
   - 리스크: 인플레이션 재반등 → 인하 지연
"""


async def send_to_slack(text: str, token: str):
    """슬랙 채널에 메시지 발송"""
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient(token=token)
    result = await client.conversations_list(types="public_channel")
    channel_id = None
    for ch in result["channels"]:
        if ch["name"] == SLACK_CHANNEL:
            channel_id = ch["id"]
            break
    if not channel_id:
        logger.error(f"Channel '{SLACK_CHANNEL}' not found")
        return
    await client.chat_postMessage(channel=channel_id, text=text, unfurl_links=False)
    logger.info(f"Sent to #{SLACK_CHANNEL}")


async def run_pipeline(report_text: str, period: str, send_slack: bool):
    """메인 파이프라인: 리포트 → 전략 추출 → 백테스트 → 발송"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")

    if not api_key:
        logger.error("ANTHROPIC_API_KEY 환경변수가 필요합니다")
        sys.exit(1)

    # ── 1단계: 리포트 → 매매전략 추출 ──
    logger.info("=" * 60)
    logger.info("1단계: 리포트에서 매매전략 추출 중...")
    logger.info("=" * 60)

    plan = await extract_strategies(report_text, api_key)

    logger.info(f"추출된 전략: {len(plan.strategies)}개")
    for s in plan.strategies:
        logger.info(f"  - {s.name}: {s.tickers} / {s.action} / 비중 {s.weight:.0%}")

    strategy_msg = format_strategies_for_slack(plan)
    print("\n" + strategy_msg + "\n")

    # ── 2단계: 백테스트 ──
    logger.info("=" * 60)
    logger.info(f"2단계: 백테스트 실행 중 (기간: {period})...")
    logger.info("=" * 60)

    results = backtest_plan(plan, period=period)

    logger.info(f"백테스트 완료: {len(results)}개 종목")
    for r in results:
        logger.info(f"  - {r.ticker}: 수익률 {r.total_return:+.1%}, 샤프 {r.sharpe:.1f}, MDD {r.max_drawdown:+.1%}")

    backtest_msg = format_backtest_for_slack(results)
    print("\n" + backtest_msg + "\n")

    # ── 3단계: 슬랙 발송 ──
    if send_slack and slack_token:
        logger.info("=" * 60)
        logger.info("3단계: 슬랙 발송 중...")
        logger.info("=" * 60)

        # 전략 도출 결과 발송
        await send_to_slack(strategy_msg, slack_token)
        # 백테스트 결과 발송
        await send_to_slack(backtest_msg, slack_token)

        logger.info("슬랙 발송 완료")
    elif send_slack and not slack_token:
        logger.warning("SLACK_BOT_TOKEN이 없어 슬랙 발송을 건너뜁니다")

    # ── 결과 JSON 저장 ──
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "strategy_results")
    os.makedirs(output_dir, exist_ok=True)

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"pipeline_{timestamp}.json")

    output_data = {
        "timestamp": timestamp,
        "market_view": {
            "sentiment": plan.market_view.overall_sentiment,
            "key_risk": plan.market_view.key_risk,
            "cash_ratio": plan.market_view.recommended_cash_ratio,
        },
        "strategies": [
            {
                "name": s.name,
                "tickers": s.tickers,
                "direction": s.direction,
                "action": s.action,
                "weight": s.weight,
                "stop_loss": s.stop_loss_pct,
                "take_profit": s.take_profit_pct,
                "holding_days": s.holding_days,
                "confidence": s.confidence,
                "rationale": s.rationale,
            }
            for s in plan.strategies
        ],
        "backtest_results": [
            {
                "ticker": r.ticker,
                "strategy": r.strategy_name,
                "total_return": r.total_return,
                "benchmark_return": r.benchmark_return,
                "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "num_trades": r.num_trades,
                "avg_hold_days": r.avg_hold_days,
                "period": f"{r.data_start} ~ {r.data_end}",
                "trades": [
                    {
                        "entry_date": t.entry_date,
                        "entry_price": t.entry_price,
                        "exit_date": t.exit_date,
                        "exit_price": t.exit_price,
                        "pnl_pct": t.pnl_pct,
                        "exit_reason": t.exit_reason,
                    }
                    for t in r.trades
                ],
            }
            for r in results
        ],
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info(f"결과 저장: {output_file}")

    return plan, results


def main():
    parser = argparse.ArgumentParser(description="투자전략 파이프라인")
    parser.add_argument("--report-file", help="리포트 텍스트 파일 경로")
    parser.add_argument("--period", default="1y", help="백테스트 기간 (6mo, 1y, 2y)")
    parser.add_argument("--no-slack", action="store_true", help="슬랙 발송 안 함")
    args = parser.parse_args()

    if args.report_file:
        with open(args.report_file, "r") as f:
            report_text = f.read()
    else:
        report_text = SAMPLE_REPORT

    asyncio.run(run_pipeline(report_text, args.period, not args.no_slack))


if __name__ == "__main__":
    main()
