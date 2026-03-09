"""
API 비용 추적 및 일일 예산 제한

모든 AI 호출의 토큰 사용량을 추적하고, 일일 예산을 초과하면 호출을 차단한다.
비용 계산: Claude Sonnet 4 기준 input $3/MTok, output $15/MTok
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("cost_tracker")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Claude Sonnet 4 pricing (per token)
PRICE_INPUT = 3.0 / 1_000_000   # $3 per 1M input tokens
PRICE_OUTPUT = 15.0 / 1_000_000  # $15 per 1M output tokens

# 일일 예산 (기본 $10 — 약 3.3M input tokens 또는 666K output tokens)
DAILY_BUDGET_USD = float(os.environ.get("DAILY_AI_BUDGET_USD", "10.0"))


class CostTracker:
    """AI API 비용 추적기"""

    def __init__(self):
        self._file = os.path.join(DATA_DIR, "cost_tracking.json")
        os.makedirs(DATA_DIR, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"daily": {}, "total_cost": 0.0, "total_calls": 0}

    def _save(self):
        # 최근 30일만 유지
        daily = self._data.get("daily", {})
        cutoff = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
        self._data["daily"] = {k: v for k, v in daily.items() if k >= cutoff}
        with open(self._file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._data, ensure_ascii=False, indent=2))

    def _today(self) -> str:
        return datetime.now(KST).strftime("%Y-%m-%d")

    def _get_today(self) -> dict:
        today = self._today()
        if today not in self._data.get("daily", {}):
            if "daily" not in self._data:
                self._data["daily"] = {}
            self._data["daily"][today] = {
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
            }
        return self._data["daily"][today]

    def can_call(self) -> bool:
        """일일 예산 내인지 확인"""
        today_data = self._get_today()
        return today_data["cost_usd"] < DAILY_BUDGET_USD

    def budget_remaining(self) -> float:
        """남은 예산 (USD)"""
        today_data = self._get_today()
        return max(0, DAILY_BUDGET_USD - today_data["cost_usd"])

    def record_usage(self, input_tokens: int, output_tokens: int, caller: str = ""):
        """API 호출 후 토큰 사용량 기록"""
        cost = (input_tokens * PRICE_INPUT) + (output_tokens * PRICE_OUTPUT)
        today_data = self._get_today()
        today_data["cost_usd"] += cost
        today_data["input_tokens"] += input_tokens
        today_data["output_tokens"] += output_tokens
        today_data["calls"] += 1
        self._data["total_cost"] = self._data.get("total_cost", 0) + cost
        self._data["total_calls"] = self._data.get("total_calls", 0) + 1
        self._save()

        if cost > 0.01:  # $0.01 이상이면 로깅
            logger.info(f"[cost] {caller}: ${cost:.4f} (in:{input_tokens}, out:{output_tokens}) | today: ${today_data['cost_usd']:.2f}/${DAILY_BUDGET_USD}")

    def get_today_stats(self) -> dict:
        today_data = self._get_today()
        return {
            "date": self._today(),
            "cost_usd": round(today_data["cost_usd"], 4),
            "budget_usd": DAILY_BUDGET_USD,
            "remaining_usd": round(self.budget_remaining(), 4),
            "usage_pct": round(today_data["cost_usd"] / DAILY_BUDGET_USD * 100, 1) if DAILY_BUDGET_USD > 0 else 0,
            "input_tokens": today_data["input_tokens"],
            "output_tokens": today_data["output_tokens"],
            "calls": today_data["calls"],
        }

    def get_summary(self) -> str:
        stats = self.get_today_stats()
        return (
            f"오늘 비용: ${stats['cost_usd']:.2f} / ${stats['budget_usd']:.2f} "
            f"({stats['usage_pct']}%) | 호출: {stats['calls']}회 | "
            f"토큰: {stats['input_tokens']:,} in / {stats['output_tokens']:,} out"
        )


# 싱글턴
_tracker: CostTracker | None = None


def get_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
