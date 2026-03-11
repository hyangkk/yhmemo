"""
시장 정보 수집 에이전트 - 공시/뉴스/블로그 자동 수집

BaseAgent를 상속하여 orchestrator에 통합.
매 사이클: 공시 수집 → 뉴스 수집 → 블로그 수집 → AI 분석 → 저장/알림

수집 소스:
- DART 전자공시 (OpenDART API)
- 네이버 금융 뉴스 RSS
- 투자 블로그 RSS
- 증권사 리포트 (네이버 리서치)
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import feedparser
import httpx

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 뉴스 RSS 소스
NEWS_RSS_SOURCES = {
    "네이버_증권": "https://news.google.com/rss/search?q=한국+증시+주식&hl=ko&gl=KR&ceid=KR:ko",
    "네이버_경제": "https://news.google.com/rss/search?q=한국+경제+금리&hl=ko&gl=KR&ceid=KR:ko",
    "네이버_반도체": "https://news.google.com/rss/search?q=반도체+삼성전자+SK하이닉스&hl=ko&gl=KR&ceid=KR:ko",
    "미국증시": "https://news.google.com/rss/search?q=미국+증시+나스닥+S%26P500&hl=ko&gl=KR&ceid=KR:ko",
}

# 투자 블로그 RSS
BLOG_RSS_SOURCES = {
    "투자_블로그1": "https://news.google.com/rss/search?q=주식+투자+전략+분석&hl=ko&gl=KR&ceid=KR:ko",
}

# 관심 종목 (공시 모니터링 대상)
WATCHLIST = [
    "005930", "000660", "005380", "000270", "006400",
    "035720", "068270", "003670", "009150", "105560",
    "051910", "066570", "035420", "028260",
]

STOCK_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차",
    "000270": "기아", "006400": "삼성SDI", "035720": "카카오",
    "068270": "셀트리온", "003670": "포스코퓨처엠", "009150": "삼성전기",
    "105560": "KB금융", "051910": "LG화학", "066570": "LG전자",
    "035420": "NAVER", "028260": "삼성물산",
}


class MarketInfoAgent(BaseAgent):
    """시장 정보 수집/분석 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, **kwargs):
        super().__init__(
            name="market_info",
            description="공시/뉴스/블로그 시장 정보 자동 수집 에이전트",
            loop_interval=int(os.environ.get("MARKET_INFO_INTERVAL", 600)),  # 10분
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self._seen_hashes: set[str] = set()
        self._dart_api_key = os.environ.get("DART_API_KEY", "")
        # secrets_vault에서 DART_API_KEY 로드 (환경변수 미설정 시)
        if not self._dart_api_key and self.supabase:
            try:
                resp = self.supabase.table("secrets_vault").select("value").eq("key", "DART_API_KEY").execute()
                if resp.data and resp.data[0].get("value"):
                    self._dart_api_key = resp.data[0]["value"]
                    logger.info("[market_info] DART_API_KEY loaded from secrets_vault")
            except Exception as e:
                logger.warning(f"[market_info] DART_API_KEY 로드 실패: {e}")
        self._http = httpx.AsyncClient(timeout=15.0)
        self._cycle = 0
        self._enabled = os.environ.get("MARKET_INFO_ENABLED", "false").lower() == "true"

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """시장 정보 수집"""
        if not self._enabled:
            return None

        self._cycle += 1
        all_items = []

        # 1) 뉴스 RSS 수집
        news_items = await self._fetch_rss(NEWS_RSS_SOURCES, "news")
        all_items.extend(news_items)

        # 2) 블로그 RSS 수집
        blog_items = await self._fetch_rss(BLOG_RSS_SOURCES, "blog")
        all_items.extend(blog_items)

        # 3) DART 공시 수집
        if self._dart_api_key:
            dart_items = await self._fetch_dart()
            all_items.extend(dart_items)

        # 중복 제거
        new_items = []
        for item in all_items:
            h = self._hash(item.get("title", "") + item.get("url", ""))
            if h not in self._seen_hashes:
                self._seen_hashes.add(h)
                new_items.append(item)

        if not new_items:
            return None

        logger.info(f"[market_info] Cycle {self._cycle}: 신규 {len(new_items)}건 수집")
        return {"items": new_items, "cycle": self._cycle}

    async def _fetch_rss(self, sources: dict, source_type: str) -> list[dict]:
        """RSS 피드 수집"""
        items = []
        for name, url in sources.items():
            try:
                resp = await self._http.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; MarketInfoBot/1.0)"
                })
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:10]:
                    items.append({
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "content": entry.get("summary", "")[:500],
                        "source": name,
                        "source_type": source_type,
                        "published": entry.get("published", ""),
                    })
            except Exception as e:
                logger.warning(f"[market_info] RSS 수집 실패 ({name}): {e}")
        return items

    async def _fetch_dart(self) -> list[dict]:
        """DART 전자공시 수집"""
        items = []
        today = datetime.now(KST).strftime("%Y%m%d")
        try:
            url = (
                f"https://opendart.fss.or.kr/api/list.json"
                f"?crtfc_key={self._dart_api_key}"
                f"&bgn_de={today}&end_de={today}"
                f"&page_count=50&sort=date&sort_mth=desc"
            )
            resp = await self._http.get(url)
            data = resp.json()
            if data.get("status") == "000":
                for item in data.get("list", []):
                    corp_code = item.get("stock_code", "")
                    # 관심 종목 공시만 수집
                    if corp_code in WATCHLIST or not WATCHLIST:
                        items.append({
                            "title": f"[공시] {item.get('corp_name', '')} - {item.get('report_nm', '')}",
                            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
                            "content": item.get("report_nm", ""),
                            "source": "DART",
                            "source_type": "disclosure",
                            "published": item.get("rcept_dt", ""),
                            "stock_code": corp_code,
                        })
        except Exception as e:
            logger.warning(f"[market_info] DART 공시 수집 실패: {e}")
        return items

    # ── Think ──────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """수집된 정보의 투자 관련성 분석"""
        items = context["items"]
        if not items:
            return None

        # AI로 투자 관련성 판단
        titles = "\n".join(f"- {i['title']} [{i['source_type']}]" for i in items[:20])

        try:
            resp = await self.ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": f"""다음 뉴스/공시 목록에서 한국 주식 투자에 중요한 정보를 선별하세요.

{titles}

## 응답 형식 (JSON)
{{"important": [
  {{"index": 0, "impact": "긍정/부정/중립", "summary": "한줄 요약", "related_stocks": ["종목코드"]}}
],
"market_outlook": "오늘 시장 전망 한줄"}}

반드시 유효한 JSON만 출력. 중요도 높은 것만 최대 5개 선별."""}],
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            analysis = json.loads(text)
            important = analysis.get("important", [])
            outlook = analysis.get("market_outlook", "")

            selected = []
            for imp in important:
                idx = imp.get("index", 0)
                if 0 <= idx < len(items):
                    item = items[idx]
                    item["impact"] = imp.get("impact", "중립")
                    item["ai_summary"] = imp.get("summary", "")
                    item["related_stocks"] = imp.get("related_stocks", [])
                    selected.append(item)

            return {
                "selected": selected,
                "all_items": items,
                "outlook": outlook,
            }

        except Exception as e:
            logger.error(f"[market_info] AI 분석 오류: {e}")
            return {"selected": [], "all_items": items, "outlook": ""}

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        """분석 결과 저장 및 알림"""
        selected = decision.get("selected", [])
        all_items = decision.get("all_items", [])
        outlook = decision.get("outlook", "")

        # 1) 전체 수집 내역 Supabase 저장
        for item in all_items:
            try:
                h = self._hash(item.get("title", "") + item.get("url", ""))
                self.supabase.table("collected_items").upsert({
                    "hash": h,
                    "title": item["title"],
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "source": item.get("source", ""),
                    "source_type": item.get("source_type", ""),
                    "metadata": json.dumps({
                        "published": item.get("published", ""),
                        "impact": item.get("impact", ""),
                        "ai_summary": item.get("ai_summary", ""),
                        "related_stocks": item.get("related_stocks", []),
                    }),
                }, on_conflict="hash").execute()
            except Exception as e:
                logger.warning(f"[market_info] DB 저장 실패: {e}")

        # 2) 중요 정보 슬랙 알림
        if selected:
            impact_emoji = {"긍정": "🟢", "부정": "🔴", "중립": "⚪"}
            lines = [f"📰 *[시장정보] 주요 뉴스/공시 ({len(selected)}건)*"]
            if outlook:
                lines.append(f"_{outlook}_")
            lines.append("")
            for item in selected[:5]:
                emoji = impact_emoji.get(item.get("impact", "중립"), "⚪")
                stocks = ", ".join(
                    STOCK_NAMES.get(s, s) for s in item.get("related_stocks", [])
                )
                stock_str = f" [{stocks}]" if stocks else ""
                lines.append(
                    f"{emoji} {item.get('ai_summary', item['title'])}{stock_str}"
                )
            await self.log("\n".join(lines))

        logger.info(
            f"[market_info] 저장 {len(all_items)}건, 중요 {len(selected)}건"
        )

    # ── 정리 ───────────────────────────────────────────

    async def cleanup(self):
        await self._http.aclose()
