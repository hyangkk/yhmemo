"""시세 데이터 수집 모듈 - yfinance 기반"""

import yfinance as yf
import pandas as pd
from config import TICKERS, BACKTEST_PERIOD, BACKTEST_INTERVAL


def fetch_data(ticker: str, period: str = BACKTEST_PERIOD, interval: str = BACKTEST_INTERVAL) -> pd.DataFrame:
    """단일 종목 OHLCV 데이터 수집"""
    stock = yf.Ticker(ticker)
    df = stock.history(period=period, interval=interval)
    df.index = df.index.tz_localize(None)
    return df


def fetch_all(tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """여러 종목 데이터 한번에 수집"""
    tickers = tickers or TICKERS
    data = {}
    for t in tickers:
        try:
            df = fetch_data(t)
            if len(df) > 50:
                data[t] = df
                print(f"  [OK] {t}: {len(df)} bars")
            else:
                print(f"  [SKIP] {t}: 데이터 부족 ({len(df)} bars)")
        except Exception as e:
            print(f"  [ERR] {t}: {e}")
    return data


def add_indicators(df: pd.DataFrame, genes: dict) -> pd.DataFrame:
    """기술적 지표 계산 (전략 유전자 기반)"""
    df = df.copy()

    # 이동평균선
    df["sma_short"] = df["Close"].rolling(window=genes["sma_short"]).mean()
    df["sma_long"] = df["Close"].rolling(window=genes["sma_long"]).mean()

    # RSI
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=genes["rsi_period"]).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=genes["rsi_period"]).mean()
    rs = gain / loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # 거래량 이동평균
    df["volume_ma"] = df["Volume"].rolling(window=genes["volume_ma"]).mean()

    # ATR (Average True Range)
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(window=genes["atr_period"]).mean()

    df.dropna(inplace=True)
    return df


if __name__ == "__main__":
    print("=== 데이터 수집 테스트 ===")
    data = fetch_all()
    for ticker, df in data.items():
        print(f"\n{ticker}: {df.shape}")
        print(df.tail(3))
