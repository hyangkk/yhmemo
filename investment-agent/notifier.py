"""노션 기록 + 슬랙 알림 모듈"""

import os
import logging
import httpx

log = logging.getLogger("invest-notifier")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class Notifier:
    """투자 에이전트 결과를 노션에 기록하고 슬랙으로 알림"""

    def __init__(self):
        self.notion_key = os.environ.get("NOTION_API_KEY", "")
        self.notion_db_id = os.environ.get("NOTION_INVEST_DB_ID", "")
        self.slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
        self.slack_channel = os.environ.get("SLACK_INVEST_CHANNEL", "ai-invest")

        self._notion_headers = {
            "Authorization": f"Bearer {self.notion_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        } if self.notion_key else {}

    def notify(self, cycle: int, results: dict):
        """노션 기록 -> 슬랙 알림 (노션 링크 포함)"""
        notion_url = None

        if self.notion_key and self.notion_db_id:
            notion_url = self._write_notion(cycle, results)

        if self.slack_token:
            self._send_slack(cycle, results, notion_url)

    def _write_notion(self, cycle: int, results: dict) -> str | None:
        """노션 데이터베이스에 결과 페이지 생성, URL 반환"""
        best = results["best_result"]
        genes = results["best_genes"]

        properties = {
            "Name": {"title": [{"text": {"content": f"Cycle {cycle}: {results['description']}"}}]},
            "Return": {"number": round(best["total_return"] * 100, 2)},
            "Sharpe": {"number": round(best["sharpe"], 2)},
            "MDD": {"number": round(best["max_drawdown"] * 100, 2)},
            "Win Rate": {"number": round(best["win_rate"] * 100, 1)},
            "Trades": {"number": best["num_trades"]},
            "Score": {"number": round(results["best_score"], 4)},
        }

        # 진화 과정을 본문 블록으로
        blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "Strategy Parameters"}}]}},
            {"type": "code", "code": {
                "rich_text": [{"text": {"content": str(genes)}}],
                "language": "json",
            }},
            {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "Evolution History"}}]}},
        ]
        for h in results.get("history", []):
            blocks.append({"type": "paragraph", "paragraph": {
                "rich_text": [{"text": {"content":
                    f"Gen {h['generation']}: score={h['best_score']:+.4f} "
                    f"return={h['best_return']:+.2%} sharpe={h['best_sharpe']:.2f}"
                }}]
            }})

        body = {
            "parent": {"database_id": self.notion_db_id},
            "properties": properties,
            "children": blocks[:100],  # Notion 블록 제한
        }

        try:
            resp = httpx.post(
                f"{NOTION_API_BASE}/pages",
                headers=self._notion_headers,
                json=body,
                timeout=30,
            )
            resp.raise_for_status()
            page = resp.json()
            page_id = page["id"].replace("-", "")
            url = f"https://notion.so/{page_id}"
            log.info(f"Notion page created: {url}")
            return url
        except Exception as e:
            log.error(f"Notion write failed: {e}")
            return None

    def _send_slack(self, cycle: int, results: dict, notion_url: str | None):
        """슬랙 채널에 결과 알림"""
        best = results["best_result"]
        score_emoji = "🔥" if results["best_score"] > 0.5 else "📊"

        text = (
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
            text += f"\n<{notion_url}|📝 Notion 상세 보기>"

        try:
            resp = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.slack_token}"},
                json={"channel": self.slack_channel, "text": text, "unfurl_links": False},
                timeout=10,
            )
            data = resp.json()
            if data.get("ok"):
                log.info(f"Slack notification sent to #{self.slack_channel}")
            else:
                log.error(f"Slack error: {data.get('error')}")
        except Exception as e:
            log.error(f"Slack send failed: {e}")
