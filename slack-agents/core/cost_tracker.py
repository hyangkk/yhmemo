"""
API 비용 추적 및 일일 예산 제한

모든 AI 호출의 토큰 사용량을 추적하고, 일일 예산을 초과하면 호출을 차단한다.
비용 계산: 모델별 가격 적용 (Haiku: $0.80/$4, Sonnet: $3/$15 per MTok)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("cost_tracker")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# 모델별 pricing (per token)
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {
        "input": 0.80 / 1_000_000,   # $0.80 per 1M input tokens
        "output": 4.0 / 1_000_000,   # $4 per 1M output tokens
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0 / 1_000_000,    # $3 per 1M input tokens
        "output": 15.0 / 1_000_000,  # $15 per 1M output tokens
    },
}
# 기본 가격 (Haiku — 대부분의 호출에 사용)
DEFAULT_PRICE_INPUT = 0.80 / 1_000_000
DEFAULT_PRICE_OUTPUT = 4.0 / 1_000_000

# 일일 예산 (기본 $20 — 프롬프트 캐싱 적용으로 실질 소비는 $10 이하 예상)
DAILY_BUDGET_USD = float(os.environ.get("DAILY_AI_BUDGET_USD", "20.0"))


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
                "cache_read_tokens": 0,
                "cache_create_tokens": 0,
                "cache_savings_usd": 0.0,
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

    def record_usage(self, input_tokens: int, output_tokens: int, caller: str = "", model: str = "",
                     cache_read_tokens: int = 0, cache_create_tokens: int = 0):
        """API 호출 후 토큰 사용량 기록 (캐시 절감 포함)"""
        pricing = MODEL_PRICING.get(model, {})
        price_in = pricing.get("input", DEFAULT_PRICE_INPUT)
        price_out = pricing.get("output", DEFAULT_PRICE_OUTPUT)
        cost = (input_tokens * price_in) + (output_tokens * price_out)

        # 캐시 히트 절감액 계산: 캐시 읽기는 원래 입력 가격의 10%만 과금
        cache_savings = cache_read_tokens * price_in * 0.9  # 90% 절감

        today_data = self._get_today()
        today_data["cost_usd"] += cost
        today_data["input_tokens"] += input_tokens
        today_data["output_tokens"] += output_tokens
        today_data["cache_read_tokens"] = today_data.get("cache_read_tokens", 0) + cache_read_tokens
        today_data["cache_create_tokens"] = today_data.get("cache_create_tokens", 0) + cache_create_tokens
        today_data["cache_savings_usd"] = today_data.get("cache_savings_usd", 0) + cache_savings
        today_data["calls"] += 1
        self._data["total_cost"] = self._data.get("total_cost", 0) + cost
        self._data["total_calls"] = self._data.get("total_calls", 0) + 1
        self._save()

        if cost > 0.01:  # $0.01 이상이면 로깅
            cache_info = f" | cache_saved: ${cache_savings:.4f}" if cache_read_tokens > 0 else ""
            logger.info(f"[cost] {caller}: ${cost:.4f} (in:{input_tokens}, out:{output_tokens}{cache_info}) | today: ${today_data['cost_usd']:.2f}/${DAILY_BUDGET_USD}")

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
            "cache_read_tokens": today_data.get("cache_read_tokens", 0),
            "cache_savings_usd": round(today_data.get("cache_savings_usd", 0), 4),
            "calls": today_data["calls"],
        }

    def get_summary(self) -> str:
        stats = self.get_today_stats()
        cache_info = ""
        if stats["cache_savings_usd"] > 0:
            cache_info = f" | 캐시 절감: ${stats['cache_savings_usd']:.2f}"
        return (
            f"오늘 비용: ${stats['cost_usd']:.2f} / ${stats['budget_usd']:.2f} "
            f"({stats['usage_pct']}%) | 호출: {stats['calls']}회 | "
            f"토큰: {stats['input_tokens']:,} in / {stats['output_tokens']:,} out"
            f"{cache_info}"
        )


# 싱글턴
_tracker: CostTracker | None = None


def get_tracker() -> CostTracker:
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
