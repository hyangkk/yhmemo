"""AI Investment Agent Configuration"""

# 투자 대상 종목 (소액 테스트용 ETF/주식)
TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]

# 백테스트 기간
BACKTEST_PERIOD = "1y"  # 1년 데이터
BACKTEST_INTERVAL = "1d"  # 일봉

# 유전 알고리즘 설정
POPULATION_SIZE = 20       # 세대당 전략 수
GENERATIONS = 10           # 진화 세대 수
MUTATION_RATE = 0.3        # 돌연변이 확률
CROSSOVER_RATE = 0.5       # 교차 확률
ELITE_RATIO = 0.2          # 상위 몇 %를 살릴지
TOURNAMENT_SIZE = 3        # 토너먼트 선택 크기

# 초기 자본금 (시뮬레이션)
INITIAL_CAPITAL = 1_000_000  # 100만원

# 수수료 (0.015% 매매 수수료)
COMMISSION_RATE = 0.00015

# 전략 파라미터 범위 (유전자 범위)
GENE_RANGES = {
    "sma_short": (5, 30),       # 단기 이동평균
    "sma_long": (20, 120),      # 장기 이동평균
    "rsi_period": (7, 28),      # RSI 기간
    "rsi_oversold": (20, 40),   # RSI 과매도
    "rsi_overbought": (60, 80), # RSI 과매수
    "stop_loss": (0.02, 0.10),  # 손절 %
    "take_profit": (0.03, 0.20),# 익절 %
    "volume_ma": (10, 30),      # 거래량 이동평균
    "atr_period": (10, 25),     # ATR 기간
    "atr_multiplier": (1.0, 3.0), # ATR 배수
}
