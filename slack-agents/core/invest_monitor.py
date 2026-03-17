"""
투자 에이전트 모니터링 & 수준 평가 시스템

오케스트레이터가 매매 에이전트(auto_trader, swing_trader)와
투자 리서치 에이전트(invest_research)의 성과를 종합 모니터링하고,
투자 전용 메트릭 기반으로 수준(등급)을 평가한다.

평가 기준:
  - 매매 에이전트: 승률, 손익, 거래 빈도, 손절/익절 비율, 학습 이행도
  - 리서치 에이전트: 분석 빈도, 주제 다양성, 매매 에이전트 참조율
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 투자 에이전트 목록
TRADING_AGENTS = ["auto_trader", "swing_trader"]
RESEARCH_AGENTS = ["invest_research"]
ALL_INVEST_AGENTS = TRADING_AGENTS + RESEARCH_AGENTS


def _now() -> datetime:
    return datetime.now(KST)


class InvestMonitor:
    """투자 에이전트 종합 모니터링 + 수준 평가"""

    def __init__(self, supabase_client, ls_client=None, ai_think_fn=None):
        self.supabase = supabase_client
        self.ls = ls_client
        self._ai_think = ai_think_fn

    # ── 매매 성과 수집 ──────────────────────────────────

    async def get_trading_metrics(self, days: int = 7) -> dict:
        """auto_trade_log에서 매매 성과 지표 수집"""
        if not self.supabase:
            return {}

        cutoff = (_now() - timedelta(days=days)).isoformat()

        try:
            resp = self.supabase.table("auto_trade_log").select(
                "trade_time,action,stock_code,stock_name,quantity,success,reason,agent_name"
            ).gte("trade_time", cutoff).order(
                "trade_time", desc=True
            ).limit(500).execute()

            trades = resp.data or []
        except Exception as e:
            logger.warning(f"[invest_monitor] 거래 이력 조회 실패: {e}")
            return {}

        # 에이전트별 통계
        metrics = {}
        for agent in TRADING_AGENTS:
            agent_trades = [
                t for t in trades
                if (t.get("agent_name") or "auto_trader") == agent
            ]
            metrics[agent] = self._calc_agent_trading_metrics(agent_trades)

        # 전체 합산
        all_trades = trades
        metrics["combined"] = self._calc_agent_trading_metrics(all_trades)

        return metrics

    def _calc_agent_trading_metrics(self, trades: list) -> dict:
        """거래 리스트에서 핵심 메트릭 계산"""
        total = len(trades)
        success_trades = [t for t in trades if t.get("success")]
        failed_trades = [t for t in trades if not t.get("success")]

        buys = [t for t in success_trades if t.get("action") == "매수"]
        sells = [t for t in success_trades if t.get("action") == "매도"]

        wins = 0
        losses = 0
        for t in sells:
            reason = (t.get("reason") or "").lower()
            if "익절" in reason:
                wins += 1
            elif "손절" in reason:
                losses += 1

        total_closed = wins + losses
        win_rate = wins / total_closed if total_closed > 0 else 0.0

        # 종목별 통계
        stock_stats = defaultdict(lambda: {"buys": 0, "sells": 0, "wins": 0, "losses": 0})
        for t in success_trades:
            code = t.get("stock_code", "")
            if not code:
                continue
            s = stock_stats[code]
            if t.get("action") == "매수":
                s["buys"] += 1
            elif t.get("action") == "매도":
                s["sells"] += 1
                reason = (t.get("reason") or "").lower()
                if "익절" in reason:
                    s["wins"] += 1
                elif "손절" in reason:
                    s["losses"] += 1

        return {
            "total_trades": total,
            "success_trades": len(success_trades),
            "failed_trades": len(failed_trades),
            "buys": len(buys),
            "sells": len(sells),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "stock_count": len(stock_stats),
            "top_traded": sorted(
                stock_stats.items(),
                key=lambda x: x[1]["buys"] + x[1]["sells"],
                reverse=True,
            )[:5],
        }

    # ── 계좌 잔고 ──────────────────────────────────────

    async def get_account_balance(self) -> dict:
        """LS증권 계좌 잔고 조회"""
        if not self.ls:
            return {}

        try:
            result = await self.ls.get_balance()
            if result.get("unavailable"):
                return {"unavailable": True, "cached": result.get("cached", False)}

            summary = result.get("summary", {})
            holdings = result.get("holdings", [])
            is_cached = result.get("cached", False)

            return {
                "total_asset": summary.get("추정순자산", 0),
                "cash": summary.get("예수금", 0),
                "stock_eval": summary.get("보유주식평가", 0),
                "pnl": summary.get("추정손익", 0),
                "orderable": summary.get("주문가능금액", 0),
                "total_buy_amount": summary.get("총매입금액", 0),
                "holding_count": len(holdings),
                "holdings": [
                    {
                        "name": h.get("종목명", ""),
                        "code": h.get("종목코드", ""),
                        "qty": h.get("잔고수량", 0),
                        "eval_amt": h.get("평가금액", 0),
                        "pnl_pct": h.get("수익률", 0),
                        "pnl_amt": h.get("평가손익", 0),
                    }
                    for h in holdings
                ],
                "cached": is_cached,
            }
        except Exception as e:
            logger.warning(f"[invest_monitor] 잔고 조회 실패: {e}")
            return {"error": str(e)}

    # ── 리서치 성과 수집 ────────────────────────────────

    async def get_research_metrics(self, days: int = 7) -> dict:
        """invest_research 에이전트의 리서치 결과물 분석"""
        if not self.supabase:
            return {}

        cutoff = (_now() - timedelta(days=days)).isoformat()

        try:
            resp = self.supabase.table("collected_items").select(
                "title,source,source_type,created_at,content"
            ).eq("source", "invest_research").gte(
                "created_at", cutoff
            ).order("created_at", desc=True).limit(100).execute()

            items = resp.data or []
        except Exception as e:
            logger.warning(f"[invest_monitor] 리서치 결과 조회 실패: {e}")
            return {}

        # 주제 다양성 분석
        topics = set()
        daily_counts = defaultdict(int)
        for item in items:
            title = item.get("title", "")
            created = item.get("created_at", "")[:10]
            daily_counts[created] += 1

            # 제목에서 주제 추출
            for topic_keyword in ["섹터", "매크로", "실적", "테마", "리스크", "포트폴리오"]:
                if topic_keyword in title:
                    topics.add(topic_keyword)

        active_days = len(daily_counts)
        total_research = len(items)
        avg_daily = total_research / max(1, active_days)

        return {
            "total_research": total_research,
            "active_days": active_days,
            "period_days": days,
            "avg_daily": round(avg_daily, 1),
            "topic_diversity": len(topics),
            "topics_covered": list(topics),
            "daily_counts": dict(daily_counts),
            "latest_titles": [item.get("title", "")[:60] for item in items[:5]],
        }

    # ── 학습 사이클 이행도 ──────────────────────────────

    async def get_learning_metrics(self, days: int = 7) -> dict:
        """trade_journal 기반 학습 사이클 이행도"""
        if not self.supabase:
            return {}

        cutoff = (_now() - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            resp = self.supabase.table("trade_journal").select(
                "journal_date,agent_name,total_trades,win_count,loss_count,total_pnl,lessons,strategy_notes"
            ).gte("journal_date", cutoff).order(
                "journal_date", desc=True
            ).limit(30).execute()

            journals = resp.data or []
        except Exception as e:
            logger.warning(f"[invest_monitor] 매매일지 조회 실패: {e}")
            return {}

        journal_days = len(set(j.get("journal_date") for j in journals))
        total_lessons = 0
        has_strategy = 0
        for j in journals:
            lessons = j.get("lessons")
            if isinstance(lessons, str):
                try:
                    lessons = json.loads(lessons)
                except (json.JSONDecodeError, TypeError):
                    lessons = []
            elif not isinstance(lessons, list):
                lessons = []
            total_lessons += len(lessons)
            if j.get("strategy_notes"):
                has_strategy += 1

        return {
            "journal_entries": len(journals),
            "journal_days": journal_days,
            "period_days": days,
            "journal_rate": journal_days / max(1, days),
            "total_lessons": total_lessons,
            "avg_lessons_per_entry": round(total_lessons / max(1, len(journals)), 1),
            "strategy_coverage": has_strategy / max(1, len(journals)),
        }

    # ── 종합 평가 ──────────────────────────────────────

    async def evaluate_invest_agents(self, days: int = 7) -> dict:
        """투자 에이전트 종합 수준 평가 (AI 기반)"""
        trading = await self.get_trading_metrics(days)
        balance = await self.get_account_balance()
        research = await self.get_research_metrics(days)
        learning = await self.get_learning_metrics(days)

        # 에이전트별 등급 계산
        grades = {}

        for agent in TRADING_AGENTS:
            m = trading.get(agent, {})
            grades[agent] = self._grade_trading_agent(m, learning)

        grades["invest_research"] = self._grade_research_agent(research)

        evaluation = {
            "timestamp": _now().isoformat(),
            "period_days": days,
            "trading_metrics": trading,
            "account_balance": balance,
            "research_metrics": research,
            "learning_metrics": learning,
            "grades": grades,
        }

        # AI 종합 분석
        if self._ai_think:
            evaluation["ai_analysis"] = await self._generate_ai_analysis(evaluation)

        return evaluation

    def _grade_trading_agent(self, metrics: dict, learning: dict) -> dict:
        """매매 에이전트 등급 계산"""
        if not metrics or metrics.get("total_trades", 0) == 0:
            return {"grade": "-", "score": 0, "reason": "거래 데이터 없음"}

        score = 0.0
        reasons = []

        # 1. 승률 (40%)
        wr = metrics.get("win_rate", 0)
        if wr >= 0.6:
            wr_score = 1.0
        elif wr >= 0.45:
            wr_score = 0.7
        elif wr >= 0.3:
            wr_score = 0.4
        else:
            wr_score = 0.1
        score += wr_score * 0.40
        reasons.append(f"승률 {wr*100:.0f}%")

        # 2. 거래 안정성 - 실패율 (20%)
        total = metrics.get("total_trades", 1)
        fail = metrics.get("failed_trades", 0)
        fail_rate = fail / max(1, total)
        stability_score = max(0, 1.0 - fail_rate * 3)
        score += stability_score * 0.20
        if fail > 0:
            reasons.append(f"주문실패 {fail}건")

        # 3. 거래 활동성 (20%)
        trades = metrics.get("total_trades", 0)
        if trades >= 10:
            activity_score = 1.0
        elif trades >= 5:
            activity_score = 0.7
        elif trades >= 1:
            activity_score = 0.4
        else:
            activity_score = 0.0
        score += activity_score * 0.20
        reasons.append(f"거래 {trades}건")

        # 4. 학습 이행도 (20%)
        journal_rate = learning.get("journal_rate", 0) if learning else 0
        score += journal_rate * 0.20
        if journal_rate > 0:
            reasons.append(f"학습이행 {journal_rate*100:.0f}%")

        grade = self._score_to_grade(score)
        return {"grade": grade, "score": round(score, 3), "reasons": reasons}

    def _grade_research_agent(self, metrics: dict) -> dict:
        """리서치 에이전트 등급 계산"""
        if not metrics or metrics.get("total_research", 0) == 0:
            return {"grade": "-", "score": 0, "reason": "리서치 데이터 없음"}

        score = 0.0
        reasons = []

        # 1. 분석 빈도 (40%) - 목표: 하루 평균 3건 이상
        avg_daily = metrics.get("avg_daily", 0)
        if avg_daily >= 3:
            freq_score = 1.0
        elif avg_daily >= 2:
            freq_score = 0.7
        elif avg_daily >= 1:
            freq_score = 0.5
        else:
            freq_score = 0.2
        score += freq_score * 0.40
        reasons.append(f"일평균 {avg_daily}건")

        # 2. 주제 다양성 (30%) - 목표: 6개 주제 중 4개 이상 커버
        diversity = metrics.get("topic_diversity", 0)
        if diversity >= 5:
            div_score = 1.0
        elif diversity >= 3:
            div_score = 0.7
        elif diversity >= 1:
            div_score = 0.4
        else:
            div_score = 0.0
        score += div_score * 0.30
        reasons.append(f"주제 {diversity}개")

        # 3. 활동일 비율 (30%)
        active_days = metrics.get("active_days", 0)
        period = metrics.get("period_days", 7)
        active_rate = active_days / max(1, period)
        score += active_rate * 0.30
        reasons.append(f"활동일 {active_days}/{period}일")

        grade = self._score_to_grade(score)
        return {"grade": grade, "score": round(score, 3), "reasons": reasons}

    def _score_to_grade(self, score: float) -> str:
        if score >= 0.85:
            return "S"
        elif score >= 0.7:
            return "A"
        elif score >= 0.5:
            return "B"
        elif score >= 0.3:
            return "C"
        else:
            return "D"

    # ── AI 종합 분석 ────────────────────────────────────

    async def _generate_ai_analysis(self, evaluation: dict) -> str:
        """AI가 투자 에이전트 종합 분석 + 개선 제안"""
        trading = evaluation.get("trading_metrics", {})
        balance = evaluation.get("account_balance", {})
        research = evaluation.get("research_metrics", {})
        learning = evaluation.get("learning_metrics", {})
        grades = evaluation.get("grades", {})

        # 요약 데이터 구성
        summary = {
            "에이전트별_등급": {
                k: {"등급": v.get("grade"), "점수": v.get("score"), "사유": v.get("reasons", [])}
                for k, v in grades.items()
            },
            "매매_요약": {
                "전체_거래": trading.get("combined", {}).get("total_trades", 0),
                "승률": f"{trading.get('combined', {}).get('win_rate', 0)*100:.0f}%",
                "익절": trading.get("combined", {}).get("wins", 0),
                "손절": trading.get("combined", {}).get("losses", 0),
            },
            "잔고": {
                "추정순자산": balance.get("total_asset", "조회불가"),
                "추정손익": balance.get("pnl", "조회불가"),
                "보유종목수": balance.get("holding_count", 0),
            },
            "리서치": {
                "총_분석": research.get("total_research", 0),
                "일평균": research.get("avg_daily", 0),
                "주제_다양성": research.get("topic_diversity", 0),
            },
            "학습": {
                "매매일지_작성율": f"{learning.get('journal_rate', 0)*100:.0f}%",
                "교훈_수": learning.get("total_lessons", 0),
            },
        }

        prompt = f"""투자 에이전트 시스템의 종합 성과를 평가하고 개선 방향을 제시하세요.

## 성과 데이터
{json.dumps(summary, ensure_ascii=False, indent=2)}

## 분석 요청
1. 전체 투자 시스템 수준 한 줄 평가
2. 각 에이전트별 강점/약점 (auto_trader, swing_trader, invest_research)
3. 가장 시급한 개선 사항 3가지
4. 구체적 전략 제안

300자 이내로 간결하게 작성하세요."""

        try:
            result = await self._ai_think(
                system_prompt="당신은 투자 시스템 감사관입니다. 데이터 기반으로 객관적 평가를 합니다.",
                user_prompt=prompt,
            )
            return result or ""
        except Exception as e:
            logger.warning(f"[invest_monitor] AI 분석 실패: {e}")
            return ""

    # ── 슬랙 보고서 포맷 ────────────────────────────────

    def format_report(self, evaluation: dict) -> str:
        """슬랙 전송용 보고서 포맷"""
        now_str = _now().strftime("%Y-%m-%d %H:%M")
        days = evaluation.get("period_days", 7)
        lines = [f"📊 *투자 에이전트 종합 현황* ({now_str}, 최근 {days}일)\n"]

        # 1. 등급 요약
        grades = evaluation.get("grades", {})
        grade_emoji = {"S": "🏆", "A": "🟢", "B": "🔵", "C": "🟡", "D": "🔴", "-": "⚪"}
        lines.append("*에이전트 수준 평가*")
        for agent, info in grades.items():
            g = info.get("grade", "-")
            emoji = grade_emoji.get(g, "⚪")
            score = info.get("score", 0)
            reasons = ", ".join(info.get("reasons", []))
            display_name = {
                "auto_trader": "자율거래(단기)",
                "swing_trader": "스윙트레이딩",
                "invest_research": "투자리서치",
            }.get(agent, agent)
            lines.append(f"  {emoji} *{display_name}*: {g}등급 ({score:.2f}) — {reasons}")

        # 2. 계좌 잔고
        balance = evaluation.get("account_balance", {})
        if balance and not balance.get("unavailable") and not balance.get("error"):
            lines.append("")
            lines.append("*계좌 현황*")
            total_asset = balance.get("total_asset", 0)
            pnl = balance.get("pnl", 0)
            cash = balance.get("cash", 0)
            stock_eval = balance.get("stock_eval", 0)
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  추정순자산: *{total_asset:,}원*")
            lines.append(f"  {pnl_emoji} 추정손익: {pnl:,}원")
            lines.append(f"  예수금: {cash:,}원 | 주식평가: {stock_eval:,}원")

            # 보유 종목
            holdings = balance.get("holdings", [])
            if holdings:
                lines.append(f"  보유 {len(holdings)}종목:")
                for h in holdings[:8]:
                    h_emoji = "🟢" if h.get("pnl_pct", 0) >= 0 else "🔴"
                    lines.append(
                        f"    {h_emoji} {h['name']} {h['qty']}주 "
                        f"{h.get('eval_amt', 0):,}원 ({h.get('pnl_pct', 0):+.1f}%)"
                    )
        elif balance.get("unavailable"):
            lines.append("\n*계좌 현황*: 장외시간 (캐시 없음)")

        # 3. 매매 통계
        trading = evaluation.get("trading_metrics", {})
        combined = trading.get("combined", {})
        if combined and combined.get("total_trades", 0) > 0:
            lines.append("")
            lines.append("*매매 성과*")
            wr = combined.get("win_rate", 0)
            lines.append(
                f"  거래 {combined['total_trades']}건 | "
                f"승률 {wr*100:.0f}% ({combined.get('wins', 0)}승 {combined.get('losses', 0)}패)"
            )
            if combined.get("failed_trades", 0) > 0:
                lines.append(f"  ⚠️ 주문 실패: {combined['failed_trades']}건")

        # 4. 리서치
        research = evaluation.get("research_metrics", {})
        if research and research.get("total_research", 0) > 0:
            lines.append("")
            lines.append("*리서치 활동*")
            lines.append(
                f"  분석 {research['total_research']}건 "
                f"(일평균 {research.get('avg_daily', 0)}건, "
                f"주제 {research.get('topic_diversity', 0)}개)"
            )

        # 5. 학습
        learning = evaluation.get("learning_metrics", {})
        if learning and learning.get("journal_entries", 0) > 0:
            lines.append("")
            lines.append("*학습 사이클*")
            lines.append(
                f"  매매일지 {learning['journal_entries']}건 "
                f"(작성률 {learning.get('journal_rate', 0)*100:.0f}%) | "
                f"교훈 {learning.get('total_lessons', 0)}개"
            )

        # 6. AI 분석
        ai_analysis = evaluation.get("ai_analysis", "")
        if ai_analysis:
            lines.append("")
            lines.append(f"*AI 종합 평가*\n{ai_analysis}")

        return "\n".join(lines)

    def format_short_report(self, evaluation: dict) -> str:
        """마스터 헬스체크용 간단 요약"""
        grades = evaluation.get("grades", {})
        grade_strs = []
        for agent in ["auto_trader", "swing_trader", "invest_research"]:
            g = grades.get(agent, {}).get("grade", "-")
            grade_strs.append(f"{agent}={g}")

        trading = evaluation.get("trading_metrics", {}).get("combined", {})
        wr = trading.get("win_rate", 0) if trading else 0
        total = trading.get("total_trades", 0) if trading else 0

        balance = evaluation.get("account_balance", {})
        pnl = balance.get("pnl", 0) if balance and not balance.get("unavailable") else "N/A"

        return (
            f"투자에이전트: {' | '.join(grade_strs)} "
            f"| 거래 {total}건 승률 {wr*100:.0f}% "
            f"| 손익 {pnl:,}원" if isinstance(pnl, int) else
            f"투자에이전트: {' | '.join(grade_strs)} "
            f"| 거래 {total}건 승률 {wr*100:.0f}% | 손익 {pnl}"
        )
