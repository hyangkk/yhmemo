"""전략 유전자(Gene) 시스템
각 전략은 유전자(파라미터 딕셔너리)로 표현되고,
교차/돌연변이를 통해 진화한다.
"""

import random
import copy
from config import GENE_RANGES, MUTATION_RATE, CROSSOVER_RATE


def random_gene() -> dict:
    """랜덤 전략 유전자 생성"""
    genes = {}
    for key, (lo, hi) in GENE_RANGES.items():
        if isinstance(lo, int):
            genes[key] = random.randint(lo, hi)
        else:
            genes[key] = round(random.uniform(lo, hi), 4)
    # sma_short < sma_long 보장
    if genes["sma_short"] >= genes["sma_long"]:
        genes["sma_short"], genes["sma_long"] = genes["sma_long"], genes["sma_short"]
        if genes["sma_short"] == genes["sma_long"]:
            genes["sma_long"] += 5
    # rsi_oversold < rsi_overbought 보장
    if genes["rsi_oversold"] >= genes["rsi_overbought"]:
        genes["rsi_oversold"], genes["rsi_overbought"] = genes["rsi_overbought"], genes["rsi_oversold"]
    return genes


def crossover(parent1: dict, parent2: dict) -> dict:
    """두 부모의 유전자를 교차하여 자식 생성"""
    child = {}
    for key in parent1:
        if random.random() < CROSSOVER_RATE:
            child[key] = parent1[key]
        else:
            child[key] = parent2[key]
    return child


def mutate(genes: dict) -> dict:
    """유전자 돌연변이"""
    genes = copy.deepcopy(genes)
    for key, (lo, hi) in GENE_RANGES.items():
        if random.random() < MUTATION_RATE:
            if isinstance(lo, int):
                # 정수: +-20% 범위 내 변이
                delta = max(1, int((hi - lo) * 0.2))
                genes[key] = max(lo, min(hi, genes[key] + random.randint(-delta, delta)))
            else:
                # 실수: +-20% 범위 내 변이
                delta = (hi - lo) * 0.2
                genes[key] = round(max(lo, min(hi, genes[key] + random.uniform(-delta, delta))), 4)
    # 제약 조건 재확인
    if genes["sma_short"] >= genes["sma_long"]:
        genes["sma_short"], genes["sma_long"] = genes["sma_long"], genes["sma_short"]
    if genes["rsi_oversold"] >= genes["rsi_overbought"]:
        genes["rsi_oversold"], genes["rsi_overbought"] = genes["rsi_overbought"], genes["rsi_oversold"]
    return genes


def generate_signal(row: dict, genes: dict, position: int) -> str:
    """단일 봉 데이터 + 유전자 -> 매매 신호 생성

    Args:
        row: OHLCV + 지표가 포함된 시리즈(dict)
        genes: 전략 파라미터
        position: 현재 포지션 (0=없음, 1=보유)

    Returns:
        "buy", "sell", "hold"
    """
    # 매수 조건: 단기MA > 장기MA AND RSI 과매도 탈출 AND 거래량 활발
    if position == 0:
        ma_cross = row["sma_short"] > row["sma_long"]
        rsi_ok = row["rsi"] < genes["rsi_overbought"]
        rsi_entry = row["rsi"] > genes["rsi_oversold"]
        vol_ok = row["Volume"] > row["volume_ma"] * 0.8

        if ma_cross and rsi_ok and rsi_entry and vol_ok:
            return "buy"

    # 매도 조건: 단기MA < 장기MA OR RSI 과매수
    if position == 1:
        ma_dead = row["sma_short"] < row["sma_long"]
        rsi_over = row["rsi"] > genes["rsi_overbought"]

        if ma_dead or rsi_over:
            return "sell"

    return "hold"


def describe_strategy(genes: dict) -> str:
    """전략을 사람이 읽을 수 있는 문자열로 설명"""
    return (
        f"SMA({genes['sma_short']}/{genes['sma_long']}) "
        f"RSI({genes['rsi_period']}, {genes['rsi_oversold']}-{genes['rsi_overbought']}) "
        f"SL:{genes['stop_loss']:.1%} TP:{genes['take_profit']:.1%} "
        f"ATR({genes['atr_period']}, x{genes['atr_multiplier']:.1f})"
    )
