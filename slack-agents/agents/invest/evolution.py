"""유전 알고리즘 진화 엔진
전략 집단을 생성 -> 백테스트 -> 선택 -> 교차/변이 -> 반복
"""

import random
import json
import os
from datetime import datetime
from strategy import random_gene, crossover, mutate, describe_strategy
from backtester import backtest_multi, fitness_score
from config import POPULATION_SIZE, GENERATIONS, ELITE_RATIO, TOURNAMENT_SIZE


def create_population(size: int = POPULATION_SIZE) -> list[dict]:
    """초기 전략 집단 생성"""
    return [random_gene() for _ in range(size)]


def evaluate_population(population: list[dict], data: dict) -> list[tuple[dict, dict, float]]:
    """전체 집단 평가 -> (유전자, 결과, 적합도) 리스트"""
    evaluated = []
    for genes in population:
        result = backtest_multi(data, genes)
        score = fitness_score(result)
        evaluated.append((genes, result, score))
    evaluated.sort(key=lambda x: x[2], reverse=True)
    return evaluated


def tournament_select(evaluated: list, k: int = TOURNAMENT_SIZE) -> dict:
    """토너먼트 선택"""
    candidates = random.sample(evaluated, min(k, len(evaluated)))
    winner = max(candidates, key=lambda x: x[2])
    return winner[0]


def evolve(data: dict, generations: int = GENERATIONS, pop_size: int = POPULATION_SIZE) -> dict:
    """메인 진화 루프

    Returns:
        dict with evolution history and best strategy
    """
    print(f"\n{'='*60}")
    print(f"  AI Investment Agent - Genetic Evolution")
    print(f"  Population: {pop_size} | Generations: {generations}")
    print(f"  Tickers: {list(data.keys())}")
    print(f"{'='*60}\n")

    population = create_population(pop_size)
    history = []
    best_ever = None
    best_score_ever = -float("inf")

    for gen in range(generations):
        # 1. 평가
        evaluated = evaluate_population(population, data)

        # 2. 통계
        scores = [e[2] for e in evaluated]
        best_genes, best_result, best_score = evaluated[0]
        avg_score = sum(scores) / len(scores)

        gen_info = {
            "generation": gen + 1,
            "best_score": best_score,
            "avg_score": avg_score,
            "best_return": best_result["total_return"],
            "best_sharpe": best_result["sharpe"],
            "best_mdd": best_result["max_drawdown"],
            "best_win_rate": best_result["win_rate"],
            "best_trades": best_result["num_trades"],
        }
        history.append(gen_info)

        # 최고 기록 갱신
        if best_score > best_score_ever:
            best_score_ever = best_score
            best_ever = (best_genes.copy(), best_result.copy(), best_score)

        # 출력
        print(f"[Gen {gen+1:3d}/{generations}] "
              f"Best: {best_score:+.4f} | Avg: {avg_score:+.4f} | "
              f"Return: {best_result['total_return']:+.2%} | "
              f"Sharpe: {best_result['sharpe']:.2f} | "
              f"MDD: {best_result['max_drawdown']:.2%} | "
              f"Trades: {best_result['num_trades']}")

        # 마지막 세대면 종료
        if gen == generations - 1:
            break

        # 3. 다음 세대 생성
        elite_count = max(2, int(pop_size * ELITE_RATIO))
        next_gen = [e[0] for e in evaluated[:elite_count]]  # 엘리트 보존

        while len(next_gen) < pop_size:
            parent1 = tournament_select(evaluated)
            parent2 = tournament_select(evaluated)
            child = crossover(parent1, parent2)
            child = mutate(child)
            next_gen.append(child)

        population = next_gen

    # 최종 결과
    best_genes, best_result, best_score = best_ever
    print(f"\n{'='*60}")
    print(f"  EVOLUTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Best Strategy: {describe_strategy(best_genes)}")
    print(f"  Total Return:  {best_result['total_return']:+.2%}")
    print(f"  Sharpe Ratio:  {best_result['sharpe']:.2f}")
    print(f"  Max Drawdown:  {best_result['max_drawdown']:.2%}")
    print(f"  Win Rate:      {best_result['win_rate']:.1%}")
    print(f"  Fitness Score: {best_score:.4f}")
    print(f"{'='*60}\n")

    return {
        "best_genes": best_genes,
        "best_result": {k: v for k, v in best_result.items() if k != "per_ticker"},
        "best_score": best_score,
        "history": history,
        "description": describe_strategy(best_genes),
    }


def save_results(results: dict, output_dir: str = "results"):
    """진화 결과 저장"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"evolution_{timestamp}.json")

    serializable = {
        "best_genes": results["best_genes"],
        "best_result": results["best_result"],
        "best_score": results["best_score"],
        "description": results["description"],
        "history": results["history"],
        "timestamp": timestamp,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)

    print(f"Results saved to: {filepath}")
    return filepath
