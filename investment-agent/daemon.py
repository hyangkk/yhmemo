#!/usr/bin/env python3
"""AI 투자 에이전트 - 상시 실행 데몬

무한 루프로 전략을 계속 진화시킴.
- 매 사이클: 데이터 갱신 -> 진화 -> 최고 전략 기록
- 세대별 챔피언은 다음 사이클의 시드로 투입 (지식 축적)
- 로그로 진행 상황 확인 가능 (fly logs)
"""

import time
import json
import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_collector import fetch_all
from evolution import evolve, save_results
from strategy import random_gene, describe_strategy
from config import GENERATIONS, POPULATION_SIZE, TICKERS
from notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("invest-daemon")

# 설정
CYCLE_INTERVAL = int(os.environ.get("CYCLE_INTERVAL", 3600))  # 사이클 간격 (초), 기본 1시간
GENS = int(os.environ.get("GENERATIONS", GENERATIONS))
POP = int(os.environ.get("POPULATION", POPULATION_SIZE))
TARGET_TICKERS = os.environ.get("TICKERS", " ".join(TICKERS)).split()

# 챔피언 저장소 (세대를 넘어 생존하는 전략들)
CHAMPION_FILE = "results/champions.json"


def load_champions() -> list[dict]:
    """이전 챔피언 전략 불러오기"""
    os.makedirs("results", exist_ok=True)
    if os.path.exists(CHAMPION_FILE):
        with open(CHAMPION_FILE, "r") as f:
            return json.load(f)
    return []


def save_champions(champions: list[dict]):
    """챔피언 전략 저장"""
    os.makedirs("results", exist_ok=True)
    with open(CHAMPION_FILE, "w") as f:
        json.dump(champions, f, indent=2, ensure_ascii=False, default=str)


def run_cycle(cycle_num: int, champions: list[dict]) -> list[dict]:
    """단일 진화 사이클 실행"""
    log.info(f"=== CYCLE {cycle_num} START ===")

    # 1. 최신 데이터 수집
    log.info("Fetching market data...")
    data = fetch_all(TARGET_TICKERS)
    if not data:
        log.error("No data available, skipping cycle")
        return champions

    # 2. 진화 실행 (챔피언을 시드로 주입)
    log.info(f"Evolving: {GENS} generations, {POP} population")
    results = evolve(data, generations=GENS, pop_size=POP)

    # 3. 결과 저장 + 노션 기록 + 슬랙 알림
    save_results(results)
    notifier.notify(cycle_num, results)

    # 4. 챔피언 갱신 - 상위 전략만 생존
    new_champion = {
        "genes": results["best_genes"],
        "score": results["best_score"],
        "return": results["best_result"]["total_return"],
        "sharpe": results["best_result"]["sharpe"],
        "mdd": results["best_result"]["max_drawdown"],
        "win_rate": results["best_result"]["win_rate"],
        "description": results["description"],
        "cycle": cycle_num,
        "timestamp": datetime.now().isoformat(),
    }

    champions.append(new_champion)
    # 상위 10개만 유지 (적합도 순)
    champions.sort(key=lambda x: x["score"], reverse=True)
    champions = champions[:10]

    save_champions(champions)

    # 5. 현황 로그
    log.info(f"--- Cycle {cycle_num} Result ---")
    log.info(f"  Strategy: {results['description']}")
    log.info(f"  Return: {results['best_result']['total_return']:+.2%}")
    log.info(f"  Sharpe: {results['best_result']['sharpe']:.2f}")
    log.info(f"  MDD: {results['best_result']['max_drawdown']:.2%}")
    log.info(f"  Score: {results['best_score']:.4f}")
    log.info(f"  Champions alive: {len(champions)}")

    if champions:
        best = champions[0]
        log.info(f"  ALL-TIME BEST: {best['description']} "
                 f"(score={best['score']:.4f}, return={best['return']:+.2%}, cycle={best['cycle']})")

    return champions


def main():
    log.info("=" * 60)
    log.info("  AI Investment Agent Daemon Starting")
    log.info(f"  Tickers: {TARGET_TICKERS}")
    log.info(f"  Generations: {GENS} | Population: {POP}")
    log.info(f"  Cycle interval: {CYCLE_INTERVAL}s")
    log.info("=" * 60)

    global notifier
    notifier = Notifier()
    if notifier.notion_key:
        log.info(f"  Notion: enabled (DB: {notifier.notion_db_id[:8]}...)")
    if notifier.slack_token:
        log.info(f"  Slack: #{notifier.slack_channel}")

    champions = load_champions()
    log.info(f"Loaded {len(champions)} previous champions")

    cycle = 1
    while True:
        try:
            champions = run_cycle(cycle, champions)
        except Exception as e:
            log.error(f"Cycle {cycle} failed: {e}", exc_info=True)

        cycle += 1
        log.info(f"Next cycle in {CYCLE_INTERVAL}s...")
        time.sleep(CYCLE_INTERVAL)


if __name__ == "__main__":
    main()
