"""매매전략 백테스터

리포트에서 추출한 TradingStrategy를 과거 데이터로 백테스트.
yfinance로 데이터를 가져와 종목별 시뮬레이션 수행.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

COMMISSION_RATE = 0.00015  # 0.015% (한국 온라인 수수료 수준)
INITIAL_CAPITAL = 10_000_000  # 1천만원


@dataclass
class Trade:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    shares: int
    pnl_pct: float
    pnl_amount: float
    exit_reason: str  # stop_loss / take_profit / holding_expired / signal


@dataclass
class BacktestResult:
    ticker: str
    strategy_name: str
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    avg_hold_days: float
    trades: list[Trade]
    equity_curve: list[float]
    benchmark_return: float  # 같은 기간 바이앤홀드 수익률
    data_start: str
    data_end: str
    data_bars: int


def fetch_price_data(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """yfinance에서 종목 데이터 조회

    Args:
        ticker: 종목 티커 (예: "005930.KS", "QQQ")
        period: 조회 기간 ("6mo", "1y", "2y", "5y")

    Returns:
        OHLCV DataFrame or None
    """
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval="1d")
        if df.empty or len(df) < 20:
            logger.warning(f"[backtest] {ticker}: 데이터 부족 ({len(df)} bars)")
            return None
        df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        logger.error(f"[backtest] {ticker} 데이터 수집 실패: {e}")
        return None


def _add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """기본 기술적 지표 추가 (범용)"""
    df = df.copy()
    df["sma_5"] = df["Close"].rolling(5).mean()
    df["sma_20"] = df["Close"].rolling(20).mean()
    df["sma_60"] = df["Close"].rolling(60).mean()

    # RSI 14
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # 변동성 (20일 표준편차)
    df["volatility"] = df["Close"].pct_change().rolling(20).std()

    df.dropna(inplace=True)
    return df


def backtest_strategy(
    ticker: str,
    strategy_name: str,
    direction: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    holding_days: int,
    weight: float = 1.0,
    period: str = "1y",
    capital: float = INITIAL_CAPITAL,
) -> BacktestResult | None:
    """단일 종목에 대해 매매전략 백테스트

    시뮬레이션 로직:
    - 진입: 백테스트 기간의 첫날 시가에 매수 (리포트 시점에 진입했다고 가정)
    - 반복 진입: 청산 후 다음 날 재진입 (전략 유효 기간 동안 반복)
    - 청산 조건: 손절 / 익절 / 보유기간 만료 중 먼저 도달하는 것

    Args:
        ticker: 종목 티커
        strategy_name: 전략명
        direction: "long" or "short"
        stop_loss_pct: 손절 % (음수, 예: -0.05)
        take_profit_pct: 익절 % (양수, 예: 0.10)
        holding_days: 최대 보유일수
        weight: 포트폴리오 비중
        period: 백테스트 기간
        capital: 투자 원금

    Returns:
        BacktestResult or None
    """
    df = fetch_price_data(ticker, period)
    if df is None:
        return None

    df = _add_technical_indicators(df)
    if len(df) < 20:
        return None

    alloc_capital = capital * weight
    cash = alloc_capital
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_idx = 0
    shares = 0

    trades: list[Trade] = []
    equity: list[float] = []

    for i, (date, row) in enumerate(df.iterrows()):
        price = row["Close"]

        # 포지션 없으면 진입
        if position == 0:
            if direction == "long":
                shares = int(cash / (price * (1 + COMMISSION_RATE)))
                if shares > 0:
                    cost = shares * price * (1 + COMMISSION_RATE)
                    cash -= cost
                    entry_price = price
                    entry_date = date
                    entry_idx = i
                    position = 1
            elif direction == "short":
                # 공매도: 주식을 빌려서 매도
                shares = int(cash / (price * (1 + COMMISSION_RATE)))
                if shares > 0:
                    cash += shares * price * (1 - COMMISSION_RATE)
                    entry_price = price
                    entry_date = date
                    entry_idx = i
                    position = -1

        # 포지션 있으면 청산 조건 체크
        elif position != 0:
            if direction == "long":
                pnl_pct = (price - entry_price) / entry_price
            else:  # short
                pnl_pct = (entry_price - price) / entry_price

            days_held = i - entry_idx
            exit_reason = None

            # 손절
            if pnl_pct <= stop_loss_pct:
                exit_reason = "stop_loss"
            # 익절
            elif pnl_pct >= take_profit_pct:
                exit_reason = "take_profit"
            # 보유기간 만료
            elif days_held >= holding_days:
                exit_reason = "holding_expired"

            if exit_reason:
                if direction == "long":
                    revenue = shares * price * (1 - COMMISSION_RATE)
                    cash += revenue
                    pnl_amount = revenue - (shares * entry_price * (1 + COMMISSION_RATE))
                else:
                    buy_back = shares * price * (1 + COMMISSION_RATE)
                    pnl_amount = (shares * entry_price * (1 - COMMISSION_RATE)) - buy_back
                    cash -= buy_back

                trades.append(Trade(
                    ticker=ticker,
                    entry_date=entry_date.strftime("%Y-%m-%d"),
                    entry_price=round(entry_price, 2),
                    exit_date=date.strftime("%Y-%m-%d"),
                    exit_price=round(price, 2),
                    shares=shares,
                    pnl_pct=round(pnl_pct, 4),
                    pnl_amount=round(pnl_amount, 0),
                    exit_reason=exit_reason,
                ))
                position = 0
                shares = 0

        # 현재 자산 기록
        if position == 1:
            current_value = cash + shares * price
        elif position == -1:
            current_value = cash - shares * price + shares * entry_price
        else:
            current_value = cash
        equity.append(current_value)

    # 마지막에 포지션 남아있으면 청산
    if position != 0 and len(df) > 0:
        last_price = df.iloc[-1]["Close"]
        last_date = df.index[-1]
        if direction == "long":
            pnl_pct = (last_price - entry_price) / entry_price
            revenue = shares * last_price * (1 - COMMISSION_RATE)
            pnl_amount = revenue - (shares * entry_price * (1 + COMMISSION_RATE))
            cash += revenue
        else:
            pnl_pct = (entry_price - last_price) / entry_price
            buy_back = shares * last_price * (1 + COMMISSION_RATE)
            pnl_amount = (shares * entry_price * (1 - COMMISSION_RATE)) - buy_back
            cash -= buy_back

        trades.append(Trade(
            ticker=ticker,
            entry_date=entry_date.strftime("%Y-%m-%d"),
            entry_price=round(entry_price, 2),
            exit_date=last_date.strftime("%Y-%m-%d"),
            exit_price=round(last_price, 2),
            shares=shares,
            pnl_pct=round(pnl_pct, 4),
            pnl_amount=round(pnl_amount, 0),
            exit_reason="end_of_period",
        ))

    final_value = cash
    total_return = (final_value - alloc_capital) / alloc_capital

    # 벤치마크: 바이앤홀드
    benchmark_return = (df.iloc[-1]["Close"] - df.iloc[0]["Close"]) / df.iloc[0]["Close"]

    # 샤프 비율
    equity_series = pd.Series(equity, index=df.index)
    daily_returns = equity_series.pct_change().dropna()
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5)

    # 최대 낙폭
    peak = equity_series.expanding().max()
    drawdown = (equity_series - peak) / peak
    max_drawdown = drawdown.min() if len(drawdown) > 0 else 0.0

    # 승률
    winning = [t for t in trades if t.pnl_pct > 0]
    win_rate = len(winning) / len(trades) if trades else 0.0

    # 평균 보유일수
    avg_hold = 0.0
    if trades:
        hold_days = []
        for t in trades:
            d1 = datetime.strptime(t.entry_date, "%Y-%m-%d")
            d2 = datetime.strptime(t.exit_date, "%Y-%m-%d")
            hold_days.append((d2 - d1).days)
        avg_hold = sum(hold_days) / len(hold_days)

    return BacktestResult(
        ticker=ticker,
        strategy_name=strategy_name,
        total_return=round(total_return, 4),
        sharpe=round(sharpe, 2),
        max_drawdown=round(max_drawdown, 4),
        win_rate=round(win_rate, 4),
        num_trades=len(trades),
        avg_hold_days=round(avg_hold, 1),
        trades=trades,
        equity_curve=equity,
        benchmark_return=round(benchmark_return, 4),
        data_start=df.index[0].strftime("%Y-%m-%d"),
        data_end=df.index[-1].strftime("%Y-%m-%d"),
        data_bars=len(df),
    )


def backtest_plan(plan, period: str = "1y", capital: float = INITIAL_CAPITAL) -> list[BacktestResult]:
    """StrategyPlan의 모든 전략을 백테스트

    Args:
        plan: StrategyPlan (report_to_strategy에서 생성)
        period: 백테스트 기간
        capital: 총 투자 원금

    Returns:
        list of BacktestResult
    """
    results = []
    for strategy in plan.strategies:
        if strategy.action == "hold":
            continue
        for ticker in strategy.tickers:
            logger.info(f"[backtest] {strategy.name} / {ticker} 백테스트 중...")
            result = backtest_strategy(
                ticker=ticker,
                strategy_name=strategy.name,
                direction=strategy.direction,
                stop_loss_pct=strategy.stop_loss_pct,
                take_profit_pct=strategy.take_profit_pct,
                holding_days=strategy.holding_days,
                weight=strategy.weight,
                period=period,
                capital=capital,
            )
            if result:
                results.append(result)
            else:
                logger.warning(f"[backtest] {ticker} 백테스트 실패 (데이터 없음)")
    return results


def format_backtest_for_slack(results: list[BacktestResult]) -> str:
    """백테스트 결과를 슬랙 메시지로 포맷팅"""
    if not results:
        return "*[백테스트 결과]* 실행 가능한 전략이 없습니다."

    lines = [
        "*[백테스트 결과]*",
        f"기간: {results[0].data_start} ~ {results[0].data_end} ({results[0].data_bars}일)",
        "",
    ]

    # 요약 테이블
    lines.append("```")
    lines.append(f"{'전략':<20} {'종목':<12} {'수익률':>8} {'벤치마크':>8} {'초과':>8} {'샤프':>6} {'MDD':>8} {'승률':>6} {'거래':>4}")
    lines.append("-" * 96)

    total_pnl = 0
    for r in results:
        excess = r.total_return - r.benchmark_return
        lines.append(
            f"{r.strategy_name:<20} {r.ticker:<12} "
            f"{r.total_return:>+7.1%} {r.benchmark_return:>+7.1%} {excess:>+7.1%} "
            f"{r.sharpe:>5.1f} {r.max_drawdown:>+7.1%} {r.win_rate:>5.0%} {r.num_trades:>4d}"
        )
        total_pnl += r.total_return

    avg_return = total_pnl / len(results) if results else 0
    lines.append("-" * 96)
    lines.append(f"{'평균':<20} {'':<12} {avg_return:>+7.1%}")
    lines.append("```")

    # 상세 거래 내역 (최근 5건씩)
    lines.append("")
    lines.append("*[주요 거래 내역]*")
    for r in results:
        if not r.trades:
            continue
        lines.append(f"\n`{r.ticker}` ({r.strategy_name}):")
        lines.append("```")
        lines.append(f"{'진입일':<12} {'진입가':>10} {'청산일':<12} {'청산가':>10} {'수익률':>8} {'사유':<16}")
        for t in r.trades[-5:]:  # 최근 5건
            reason_kr = {
                "stop_loss": "손절",
                "take_profit": "익절",
                "holding_expired": "보유기간만료",
                "end_of_period": "기간종료",
                "signal": "시그널",
            }.get(t.exit_reason, t.exit_reason)
            lines.append(
                f"{t.entry_date:<12} {t.entry_price:>10,.0f} "
                f"{t.exit_date:<12} {t.exit_price:>10,.0f} "
                f"{t.pnl_pct:>+7.1%} {reason_kr:<16}"
            )
        lines.append("```")

    # 종합 평가
    lines.append("")
    profitable = [r for r in results if r.total_return > 0]
    lines.append(f"*[종합]* {len(results)}개 전략 중 {len(profitable)}개 수익 | "
                 f"평균 수익률 {avg_return:+.1%} | "
                 f"평균 샤프 {sum(r.sharpe for r in results)/len(results):.1f}")

    return "\n".join(lines)
