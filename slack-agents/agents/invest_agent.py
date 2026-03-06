"""
투자 에이전트 - 유전 알고리즘 기반 전략 자동 진화

BaseAgent를 상속하여 orchestrator에 통합.
매 사이클: 시세 수집 -> 전략 진화 -> 노션 기록 -> 슬랙 알림

TODO: Fly.io 독립 앱(yhmemo-invest-agent) 아직 안 지움. `fly apps destroy yhmemo-invest-agent --yes` 실행 필요
"""

import json
import os
import logging
from datetime import datetime

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# invest 모듈 임포트 경로 설정
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "invest"))

from agents.invest.data_collector import fetch_all
from agents.invest.evolution import evolve, save_results
from agents.invest.strategy import describe_strategy
from agents.invest.config import GENERATIONS, POPULATION_SIZE, TICKERS

CHAMPION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "invest_champions.json")


class InvestAgent(BaseAgent):
    """유전 알고리즘으로 투자 전략을 진화시키는 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, **kwargs):
        super().__init__(
            name="invest",
            description="유전 알고리즘 기반 투자 전략 자동 진화",
            loop_interval=int(os.environ.get("INVEST_INTERVAL", 3600)),
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self.generations = int(os.environ.get("INVEST_GENERATIONS", GENERATIONS))
        self.population = int(os.environ.get("INVEST_POPULATION", POPULATION_SIZE))
        self.tickers = os.environ.get("INVEST_TICKERS", " ".join(TICKERS)).split()
        self.champions = self._load_champions()
        self.cycle = 1
        self.notion_db_id = os.environ.get("NOTION_INVEST_DB_ID", "")

    async def observe(self) -> dict | None:
        """시세 데이터 수집"""
        logger.info(f"[invest] Cycle {self.cycle}: fetching data for {self.tickers}")
        data = fetch_all(self.tickers)
        if not data:
            logger.error("[invest] No market data available")
            return None
        return {"data": data, "cycle": self.cycle}

    async def think(self, context: dict) -> dict | None:
        """전략 진화 실행"""
        data = context["data"]
        logger.info(f"[invest] Evolving: {self.generations} gens, {self.population} pop")
        results = evolve(data, generations=self.generations, pop_size=self.population)
        return {"results": results, "cycle": context["cycle"]}

    async def act(self, decision: dict):
        """결과 저장 + 노션 기록 + 슬랙 알림"""
        results = decision["results"]
        cycle = decision["cycle"]

        # 1. 파일 저장
        os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data", "invest_results"), exist_ok=True)
        save_dir = os.path.join(os.path.dirname(__file__), "..", "data", "invest_results")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(save_dir, f"evolution_{timestamp}.json")
        with open(filepath, "w") as f:
            json.dump({
                "best_genes": results["best_genes"],
                "best_result": results["best_result"],
                "best_score": results["best_score"],
                "description": results["description"],
                "history": results["history"],
            }, f, indent=2, default=str)

        # 2. 챔피언 갱신
        best = results["best_result"]
        self.champions.append({
            "genes": results["best_genes"],
            "score": results["best_score"],
            "return": best["total_return"],
            "sharpe": best["sharpe"],
            "mdd": best["max_drawdown"],
            "win_rate": best["win_rate"],
            "description": results["description"],
            "cycle": cycle,
            "timestamp": datetime.now().isoformat(),
        })
        self.champions.sort(key=lambda x: x["score"], reverse=True)
        self.champions = self.champions[:10]
        self._save_champions()

        # 3. 노션 기록
        notion_url = None
        if self.notion and self.notion_db_id:
            notion_url = await self._write_notion(cycle, results)

        # 4. 슬랙 알림
        score_emoji = "🔥" if results["best_score"] > 0.5 else "📊"
        msg = (
            f"{score_emoji} *Investment Agent - Cycle {cycle}*\n"
            f"```\n"
            f"Strategy: {results['description']}\n"
            f"Return:   {best['total_return']:+.2%}\n"
            f"Sharpe:   {best['sharpe']:.2f}\n"
            f"MDD:      {best['max_drawdown']:.2%}\n"
            f"Win Rate: {best['win_rate']:.1%}\n"
            f"Score:    {results['best_score']:.4f}\n"
            f"```"
        )
        if notion_url:
            msg += f"\n<{notion_url}|📝 Notion 상세 보기>"

        if self.champions:
            all_time = self.champions[0]
            msg += f"\n\n*All-time best:* {all_time['description']} (cycle {all_time['cycle']}, score {all_time['score']:.4f})"

        await self.say(msg)
        logger.info(f"[invest] Cycle {cycle} complete: score={results['best_score']:.4f}")
        self.cycle += 1

    async def _write_notion(self, cycle: int, results: dict) -> str | None:
        """노션에 결과 페이지 생성"""
        best = results["best_result"]
        try:
            properties = {
                "Name": self.notion.prop_title(f"Cycle {cycle}: {results['description']}"),
                "Return": self.notion.prop_number(round(best["total_return"] * 100, 2)),
                "Sharpe": self.notion.prop_number(round(best["sharpe"], 2)),
                "MDD": self.notion.prop_number(round(best["max_drawdown"] * 100, 2)),
                "Win Rate": self.notion.prop_number(round(best["win_rate"] * 100, 1)),
                "Trades": self.notion.prop_number(best["num_trades"]),
                "Score": self.notion.prop_number(round(results["best_score"], 4)),
            }
            blocks = [
                self.notion.block_heading("Strategy Parameters"),
                self.notion.block_paragraph(str(results["best_genes"])),
                self.notion.block_heading("Evolution History"),
            ]
            for h in results.get("history", [])[-5:]:
                blocks.append(self.notion.block_paragraph(
                    f"Gen {h['generation']}: score={h['best_score']:+.4f} "
                    f"return={h['best_return']:+.2%}"
                ))

            page = await self.notion.create_page(self.notion_db_id, properties, blocks)
            if page:
                page_id = page["id"].replace("-", "")
                return f"https://notion.so/{page_id}"
        except Exception as e:
            logger.error(f"[invest] Notion write failed: {e}")
        return None

    def _load_champions(self) -> list[dict]:
        try:
            with open(CHAMPION_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_champions(self):
        os.makedirs(os.path.dirname(CHAMPION_FILE), exist_ok=True)
        with open(CHAMPION_FILE, "w") as f:
            json.dump(self.champions, f, indent=2, default=str)
