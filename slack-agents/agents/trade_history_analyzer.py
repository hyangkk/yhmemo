"""
거래 이력 분석 모듈 - 학습 사이클의 핵심

auto_trade_log에서 과거 거래를 읽어 통계를 계산하고,
trade_journal에서 매매일지/교훈을 관리한다.
AutoTrader와 SwingTrader 양쪽에서 공용으로 사용.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class TradeHistoryAnalyzer:
    """과거 거래 이력 분석 및 매매일지 관리"""

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # ── 통계 조회 ──────────────────────────────────────

    async def get_stock_stats(self, days: int = 30) -> dict:
        """종목별 매매 통계 (최근 N일)

        Returns:
            {
                "종목코드": {
                    "name": "삼성전자",
                    "trades": 10,
                    "sells": 5,
                    "wins": 3,     # reason에 '익절' 포함
                    "losses": 2,   # reason에 '손절' 포함
                    "win_rate": 0.6,
                },
                ...
            }
        """
        if not self.supabase:
            return {}

        cutoff = (datetime.now(KST) - timedelta(days=days)).isoformat()

        try:
            resp = self.supabase.table("auto_trade_log").select(
                "stock_code,stock_name,action,success,reason"
            ).gte("trade_time", cutoff).eq("success", True).order(
                "trade_time", desc=True
            ).limit(500).execute()

            trades = resp.data or []
        except Exception as e:
            logger.warning(f"[analyzer] 거래 이력 조회 실패: {e}")
            return {}

        stats = defaultdict(lambda: {
            "name": "", "trades": 0, "sells": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
        })

        for t in trades:
            code = t.get("stock_code", "")
            if not code:
                continue
            s = stats[code]
            s["name"] = t.get("stock_name", "") or s["name"]
            s["trades"] += 1

            if t.get("action") == "매도":
                s["sells"] += 1
                reason = (t.get("reason") or "").lower()
                if "익절" in reason:
                    s["wins"] += 1
                elif "손절" in reason:
                    s["losses"] += 1

        # 승률 계산
        for code, s in stats.items():
            total_closed = s["wins"] + s["losses"]
            s["win_rate"] = s["wins"] / total_closed if total_closed > 0 else 0.0

        return dict(stats)

    async def get_overall_stats(self, days: int = 30) -> dict:
        """전체 통계 요약"""
        stock_stats = await self.get_stock_stats(days)

        total_trades = sum(s["trades"] for s in stock_stats.values())
        total_sells = sum(s["sells"] for s in stock_stats.values())
        total_wins = sum(s["wins"] for s in stock_stats.values())
        total_losses = sum(s["losses"] for s in stock_stats.values())

        # 최다 손실 종목
        worst = sorted(
            stock_stats.items(),
            key=lambda x: x[1]["losses"],
            reverse=True,
        )[:3]

        # 최고 승률 종목 (매도 3건 이상)
        best = sorted(
            [(c, s) for c, s in stock_stats.items() if s["sells"] >= 3],
            key=lambda x: x[1]["win_rate"],
            reverse=True,
        )[:3]

        return {
            "total_trades": total_trades,
            "total_sells": total_sells,
            "total_wins": total_wins,
            "total_losses": total_losses,
            "overall_win_rate": total_wins / (total_wins + total_losses) if (total_wins + total_losses) > 0 else 0,
            "worst_stocks": [(c, s["name"], s["losses"]) for c, s in worst if s["losses"] > 0],
            "best_stocks": [(c, s["name"], s["win_rate"]) for c, s in best],
            "per_stock": stock_stats,
        }

    # ── 매매일지 관리 ──────────────────────────────────

    async def get_recent_lessons(self, days: int = 7) -> list[str]:
        """최근 N일간의 교훈 목록"""
        if not self.supabase:
            return []

        cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            resp = self.supabase.table("trade_journal").select(
                "journal_date,lessons,strategy_notes"
            ).gte("journal_date", cutoff).order(
                "journal_date", desc=True
            ).limit(days).execute()

            lessons = []
            for j in (resp.data or []):
                date = j.get("journal_date", "")
                for lesson in (j.get("lessons") or []):
                    lessons.append(f"[{date}] {lesson}")
            return lessons
        except Exception as e:
            logger.warning(f"[analyzer] 교훈 조회 실패: {e}")
            return []

    async def get_yesterday_journal(self) -> dict | None:
        """전일 매매일지 로드"""
        if not self.supabase:
            return None

        yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")

        try:
            resp = self.supabase.table("trade_journal").select("*").eq(
                "journal_date", yesterday
            ).limit(1).execute()

            if resp.data:
                return resp.data[0]
            return None
        except Exception as e:
            logger.warning(f"[analyzer] 전일 일지 조회 실패: {e}")
            return None

    async def save_journal(self, date: str, analysis: dict):
        """매매일지 저장 (upsert)"""
        if not self.supabase:
            return

        try:
            self.supabase.table("trade_journal").upsert({
                "journal_date": date,
                "agent_name": "combined",
                "total_trades": analysis.get("total_trades", 0),
                "win_count": analysis.get("win_count", 0),
                "loss_count": analysis.get("loss_count", 0),
                "total_pnl": analysis.get("total_pnl", 0),
                "net_asset": analysis.get("net_asset", 0),
                "lessons": json.dumps(
                    analysis.get("lessons", []), ensure_ascii=False
                ),
                "strategy_notes": analysis.get("strategy_notes", ""),
                "raw_analysis": analysis.get("raw_analysis", ""),
            }, on_conflict="journal_date,agent_name").execute()
            logger.info(f"[analyzer] 매매일지 저장 완료: {date}")
        except Exception as e:
            logger.warning(f"[analyzer] 매매일지 저장 실패: {e}")

    # ── 프롬프트용 포맷팅 ──────────────────────────────

    def format_stats_for_prompt(self, stats: dict) -> str:
        """통계를 AI 프롬프트 삽입용 텍스트로 변환"""
        if not stats:
            return "과거 거래 데이터 없음"

        overall_wins = sum(s["wins"] for s in stats.values())
        overall_losses = sum(s["losses"] for s in stats.values())
        total = overall_wins + overall_losses
        overall_rate = overall_wins / total * 100 if total > 0 else 0

        lines = [f"전체 승률: {overall_rate:.0f}% ({overall_wins}승 {overall_losses}패, 총 {total}건 매도)"]

        # 종목별 상세 (매도 2건 이상만)
        for code, s in sorted(stats.items(), key=lambda x: x[1]["sells"], reverse=True):
            if s["sells"] < 2:
                continue
            rate = s["win_rate"] * 100
            lines.append(
                f"  {s['name']}({code}): 승률 {rate:.0f}% "
                f"({s['wins']}승 {s['losses']}패/{s['sells']}건 매도)"
            )

        return "\n".join(lines[:10])  # 최대 10줄

    def format_lessons_for_prompt(self, lessons: list[str]) -> str:
        """교훈 목록을 프롬프트용 텍스트로 변환"""
        if not lessons:
            return "이전 교훈 없음"
        return "\n".join(f"- {l}" for l in lessons[:7])
