"""백테스트 엔진
전략 유전자를 받아 과거 데이터로 시뮬레이션 수행
"""

import pandas as pd
from data_collector import add_indicators
from strategy import generate_signal
from config import INITIAL_CAPITAL, COMMISSION_RATE


def backtest(df: pd.DataFrame, genes: dict, initial_capital: float = INITIAL_CAPITAL) -> dict:
    """단일 종목에 대해 전략 백테스트 실행

    Returns:
        dict with keys: total_return, sharpe, max_drawdown, win_rate, trades, equity_curve
    """
    df = add_indicators(df, genes)
    if len(df) < 10:
        return _empty_result()

    capital = initial_capital
    position = 0        # 0=현금, 1=보유
    entry_price = 0.0
    shares = 0

    trades = []
    equity = []

    for i, (idx, row) in enumerate(df.iterrows()):
        row_dict = row.to_dict()
        signal = generate_signal(row_dict, genes, position)

        if signal == "buy" and position == 0:
            shares = int(capital / row["Close"])
            if shares > 0:
                cost = shares * row["Close"] * (1 + COMMISSION_RATE)
                capital -= cost
                entry_price = row["Close"]
                position = 1

        elif signal == "sell" and position == 1:
            revenue = shares * row["Close"] * (1 - COMMISSION_RATE)
            capital += revenue
            pnl = (row["Close"] - entry_price) / entry_price
            trades.append({"entry": entry_price, "exit": row["Close"], "pnl": pnl})
            position = 0
            shares = 0

        # 손절/익절 체크
        elif position == 1:
            pnl_pct = (row["Close"] - entry_price) / entry_price
            if pnl_pct <= -genes["stop_loss"] or pnl_pct >= genes["take_profit"]:
                revenue = shares * row["Close"] * (1 - COMMISSION_RATE)
                capital += revenue
                trades.append({"entry": entry_price, "exit": row["Close"], "pnl": pnl_pct})
                position = 0
                shares = 0

        # 현재 자산 기록
        current_value = capital + (shares * row["Close"] if position == 1 else 0)
        equity.append(current_value)

    # 마지막에 포지션 남아있으면 청산
    if position == 1 and len(df) > 0:
        last_price = df.iloc[-1]["Close"]
        revenue = shares * last_price * (1 - COMMISSION_RATE)
        capital += revenue
        pnl = (last_price - entry_price) / entry_price
        trades.append({"entry": entry_price, "exit": last_price, "pnl": pnl})

    final_value = capital
    equity_series = pd.Series(equity, index=df.index)

    return _calc_metrics(initial_capital, final_value, equity_series, trades)


def backtest_multi(data: dict[str, pd.DataFrame], genes: dict) -> dict:
    """여러 종목에 대해 백테스트하고 평균 성과 계산"""
    results = {}
    for ticker, df in data.items():
        results[ticker] = backtest(df, genes)

    if not results:
        return _empty_result()

    avg_return = sum(r["total_return"] for r in results.values()) / len(results)
    avg_sharpe = sum(r["sharpe"] for r in results.values()) / len(results)
    avg_drawdown = sum(r["max_drawdown"] for r in results.values()) / len(results)
    total_trades = sum(r["num_trades"] for r in results.values())
    win_rates = [r["win_rate"] for r in results.values() if r["num_trades"] > 0]
    avg_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0

    return {
        "total_return": avg_return,
        "sharpe": avg_sharpe,
        "max_drawdown": avg_drawdown,
        "win_rate": avg_win_rate,
        "num_trades": total_trades,
        "per_ticker": results,
    }


def fitness_score(result: dict) -> float:
    """적합도 점수 계산 (높을수록 좋음)
    수익률, 샤프비율, MDD를 종합 평가
    """
    ret = result["total_return"]
    sharpe = result["sharpe"]
    mdd = result["max_drawdown"]
    trades = result["num_trades"]

    # 거래가 너무 적으면 패널티
    if trades < 3:
        return -999

    # 적합도 = 수익률*40% + 샤프*30% - MDD*20% + 거래빈도보정*10%
    score = (ret * 0.4) + (sharpe * 0.3) - (abs(mdd) * 0.2)
    return score


def _calc_metrics(initial: float, final: float, equity: pd.Series, trades: list) -> dict:
    total_return = (final - initial) / initial

    # 일별 수익률
    daily_returns = equity.pct_change().dropna()
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * (252 ** 0.5)

    # 최대 낙폭
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak
    max_drawdown = drawdown.min() if len(drawdown) > 0 else 0

    # 승률
    winning = [t for t in trades if t["pnl"] > 0]
    win_rate = len(winning) / len(trades) if trades else 0

    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "num_trades": len(trades),
        "final_value": final,
    }


def _empty_result() -> dict:
    return {
        "total_return": 0,
        "sharpe": 0,
        "max_drawdown": 0,
        "win_rate": 0,
        "num_trades": 0,
        "final_value": 0,
    }
