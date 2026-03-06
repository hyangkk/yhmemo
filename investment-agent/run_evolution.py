#!/usr/bin/env python3
"""AI 투자 에이전트 - 메인 실행 스크립트

사용법:
    python run_evolution.py                    # 기본 실행
    python run_evolution.py --generations 20   # 세대 수 조정
    python run_evolution.py --tickers SPY QQQ  # 종목 지정
    python run_evolution.py --quick            # 빠른 테스트 (5세대, 10개체)
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_collector import fetch_all
from evolution import evolve, save_results
from strategy import describe_strategy
from config import GENERATIONS, POPULATION_SIZE, TICKERS


def main():
    parser = argparse.ArgumentParser(description="AI Investment Agent - Genetic Strategy Evolution")
    parser.add_argument("--generations", "-g", type=int, default=GENERATIONS, help="진화 세대 수")
    parser.add_argument("--population", "-p", type=int, default=POPULATION_SIZE, help="세대당 전략 수")
    parser.add_argument("--tickers", "-t", nargs="+", default=TICKERS, help="투자 대상 종목")
    parser.add_argument("--quick", "-q", action="store_true", help="빠른 테스트 모드")
    args = parser.parse_args()

    if args.quick:
        args.generations = 5
        args.population = 10

    # 1. 데이터 수집
    print("\n[Phase 1] 시세 데이터 수집")
    print("-" * 40)
    data = fetch_all(args.tickers)

    if not data:
        print("ERROR: 데이터를 수집할 수 없습니다.")
        sys.exit(1)

    print(f"\n총 {len(data)}개 종목 데이터 준비 완료")

    # 2. 유전 알고리즘 진화
    print(f"\n[Phase 2] 전략 진화 시작")
    print("-" * 40)
    results = evolve(data, generations=args.generations, pop_size=args.population)

    # 3. 결과 저장
    print(f"\n[Phase 3] 결과 저장")
    print("-" * 40)
    filepath = save_results(results)

    # 4. 최종 요약
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  최적 전략: {results['description']}")
    print(f"  파라미터: {results['best_genes']}")
    print(f"\n  성과:")
    r = results["best_result"]
    print(f"    수익률:     {r['total_return']:+.2%}")
    print(f"    샤프비율:   {r['sharpe']:.2f}")
    print(f"    최대낙폭:   {r['max_drawdown']:.2%}")
    print(f"    승률:       {r['win_rate']:.1%}")
    print(f"    총 거래수:  {r['num_trades']}")
    print(f"\n  진화 과정:")
    for h in results["history"]:
        print(f"    Gen {h['generation']:3d}: "
              f"best={h['best_score']:+.4f} avg={h['avg_score']:+.4f} "
              f"return={h['best_return']:+.2%}")
    print(f"\n  결과 파일: {filepath}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
