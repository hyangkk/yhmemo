"""
투자전략 연구 에이전트 - 자율 정보 수집 + 전략 분석

매매 에이전트와 독립적으로 24시간 투자 리서치 수행:
- 단기/중장기 투자전략 수립을 위한 정보 자율 수집
- DART 공시, 뉴스, 웹 검색, 섹터 분석 등
- 분석 결과를 노션 + Supabase에 저장
- 매매 에이전트가 참조할 수 있는 구조화된 인사이트 생성

사이클:
1. 리서치 주제 자율 결정 (AI가 무엇을 조사할지 판단)
2. 정보 수집 (DART, 뉴스 RSS, 웹 검색)
3. 분석 및 인사이트 추출
4. 결과물 저장 (노션 + Supabase)
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx
import feedparser

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 관심 종목
WATCH_STOCKS = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차",
    "000270": "기아", "006400": "삼성SDI", "035720": "카카오",
    "068270": "셀트리온", "003670": "포스코퓨처엠", "009150": "삼성전기",
    "105560": "KB금융", "051910": "LG화학", "066570": "LG전자",
    "035420": "NAVER", "028260": "삼성물산", "012330": "현대모비스",
    "055550": "신한지주", "373220": "LG에너지솔루션", "207940": "삼성바이오로직스",
}

# 리서치 소스
RESEARCH_SOURCES = {
    "매크로": "https://news.google.com/rss/search?q=한국+경제+금리+환율+GDP&hl=ko&gl=KR&ceid=KR:ko",
    "반도체산업": "https://news.google.com/rss/search?q=반도체+HBM+AI칩+파운드리+TSMC&hl=ko&gl=KR&ceid=KR:ko",
    "2차전지": "https://news.google.com/rss/search?q=2차전지+배터리+전기차+LFP+전고체&hl=ko&gl=KR&ceid=KR:ko",
    "미국증시": "https://news.google.com/rss/search?q=나스닥+S%26P500+연준+금리+트럼프&hl=ko&gl=KR&ceid=KR:ko",
    "글로벌이슈": "https://news.google.com/rss/search?q=지정학+관세+무역+중국+미국&hl=ko&gl=KR&ceid=KR:ko",
    "밸류업": "https://news.google.com/rss/search?q=밸류업+자사주+배당+주주환원+기업지배구조&hl=ko&gl=KR&ceid=KR:ko",
}

# 리서치 주제 (순환)
RESEARCH_TOPICS = [
    "sector_rotation",      # 섹터 로테이션 분석
    "macro_outlook",        # 매크로 경제 전망
    "earnings_analysis",    # 실적/공시 분석
    "theme_discovery",      # 새로운 투자 테마 발굴
    "risk_assessment",      # 리스크 요인 점검
    "portfolio_review",     # 포트폴리오 최적화 제안
]


class InvestResearchAgent(BaseAgent):
    """자율 투자전략 연구 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, ls_client=None, **kwargs):
        super().__init__(
            name="invest_research",
            description="자율 투자전략 연구 - 정보 수집, 분석, 인사이트 생성",
            loop_interval=int(os.environ.get("INVEST_RESEARCH_INTERVAL", 3600)),  # 기본 1시간
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self.ls = ls_client
        self._http = httpx.AsyncClient(timeout=30.0)
        self._cycle = 0
        self._topic_index = 0
        self._seen_news: set[str] = set()
        self._last_dart_check = ""
        self._enabled = os.environ.get("INVEST_RESEARCH_ENABLED", "true").lower() == "true"

    def _now(self) -> datetime:
        return datetime.now(KST)

    def _current_topic(self) -> str:
        topic = RESEARCH_TOPICS[self._topic_index % len(RESEARCH_TOPICS)]
        self._topic_index += 1
        return topic

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        if not self._enabled:
            return None

        self._cycle += 1
        topic = self._current_topic()

        context = {
            "cycle": self._cycle,
            "topic": topic,
            "now": self._now().isoformat(),
        }

        # 1) 뉴스 수집 (해당 주제 관련)
        news = await self._collect_news(topic)
        context["news"] = news

        # 2) DART 공시 (하루 1회)
        today = self._now().strftime("%Y%m%d")
        if today != self._last_dart_check:
            dart_items = await self._collect_dart()
            context["disclosures"] = dart_items
            self._last_dart_check = today
        else:
            context["disclosures"] = []

        # 3) 최근 매매 성과 (매매 에이전트와 연동)
        trade_stats = await self._get_recent_trade_stats()
        context["trade_stats"] = trade_stats

        # 4) 최근 리서치 (중복 방지)
        recent_research = await self._get_recent_research()
        context["recent_research"] = recent_research

        return context

    async def _collect_news(self, topic: str) -> list[dict]:
        """주제 관련 뉴스 RSS 수집"""
        items = []
        # 주제에 맞는 소스 선택
        source_map = {
            "sector_rotation": ["반도체산업", "2차전지", "밸류업"],
            "macro_outlook": ["매크로", "미국증시", "글로벌이슈"],
            "earnings_analysis": ["반도체산업", "2차전지"],
            "theme_discovery": ["반도체산업", "2차전지", "글로벌이슈", "밸류업"],
            "risk_assessment": ["매크로", "글로벌이슈", "미국증시"],
            "portfolio_review": ["반도체산업", "2차전지", "밸류업"],
        }
        sources = source_map.get(topic, list(RESEARCH_SOURCES.keys())[:3])

        for src_name in sources:
            url = RESEARCH_SOURCES.get(src_name)
            if not url:
                continue
            try:
                resp = await self._http.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; InvestResearch/1.0)"
                })
                feed = feedparser.parse(resp.text)
                for entry in feed.entries[:10]:
                    title = entry.get("title", "")
                    key = title[:50]
                    if key not in self._seen_news:
                        self._seen_news.add(key)
                        items.append({
                            "title": title,
                            "url": entry.get("link", ""),
                            "source": src_name,
                            "published": entry.get("published", ""),
                        })
            except Exception as e:
                logger.warning(f"[research] RSS 수집 실패 ({src_name}): {e}")

        # 메모리 관리: seen_news 최대 500개
        if len(self._seen_news) > 500:
            self._seen_news = set(list(self._seen_news)[-300:])

        return items

    async def _collect_dart(self) -> list[dict]:
        """DART 주요 공시 수집"""
        items = []
        dart_key = os.environ.get("DART_API_KEY", "")
        if not dart_key and self.supabase:
            try:
                resp = self.supabase.table("secrets_vault").select("value").eq("key", "DART_API_KEY").execute()
                if resp.data:
                    dart_key = resp.data[0].get("value", "")
            except Exception:
                pass

        if not dart_key:
            return items

        today = self._now().strftime("%Y%m%d")
        try:
            url = (
                f"https://opendart.fss.or.kr/api/list.json"
                f"?crtfc_key={dart_key}"
                f"&bgn_de={today}&end_de={today}"
                f"&page_count=100&sort=date&sort_mth=desc"
            )
            resp = await self._http.get(url)
            data = resp.json()
            if data.get("status") == "000":
                watchlist = set(WATCH_STOCKS.keys())
                for item in data.get("list", []):
                    sc = item.get("stock_code", "")
                    if sc in watchlist:
                        items.append({
                            "title": f"{item.get('corp_name','')} - {item.get('report_nm','')}",
                            "stock_code": sc,
                            "rcept_no": item.get("rcept_no", ""),
                        })
        except Exception as e:
            logger.warning(f"[research] DART 수집 실패: {e}")
        return items

    async def _get_recent_trade_stats(self) -> dict:
        """최근 매매 성과 가져오기 (매매 에이전트 연동)"""
        if not self.supabase:
            return {}

        try:
            cutoff = (self._now() - timedelta(days=7)).isoformat()
            resp = self.supabase.table("auto_trade_log").select(
                "stock_code,stock_name,action,success,reason"
            ).gte("trade_time", cutoff).eq("success", True).order(
                "trade_time", desc=True
            ).limit(50).execute()

            trades = resp.data or []
            # 종목별 간단 통계
            stock_trades = {}
            for t in trades:
                code = t.get("stock_code", "")
                if code not in stock_trades:
                    stock_trades[code] = {"name": t.get("stock_name", ""), "buys": 0, "sells": 0}
                if t["action"] == "매수":
                    stock_trades[code]["buys"] += 1
                else:
                    stock_trades[code]["sells"] += 1

            return {"recent_7d": stock_trades, "total_trades": len(trades)}
        except Exception as e:
            logger.warning(f"[research] 매매 통계 조회 실패: {e}")
            return {}

    async def _get_recent_research(self) -> list[str]:
        """최근 리서치 주제 (중복 방지용)"""
        if not self.supabase:
            return []

        try:
            cutoff = (self._now() - timedelta(days=3)).isoformat()
            resp = self.supabase.table("collected_items").select(
                "title"
            ).eq("source", "invest_research").gte(
                "created_at", cutoff
            ).order("created_at", desc=True).limit(10).execute()

            return [r["title"] for r in (resp.data or [])]
        except Exception:
            return []

    # ── Think ──────────────────────────────────────────

    async def think(self, ctx: dict) -> dict | None:
        topic = ctx.get("topic", "")
        news = ctx.get("news", [])
        disclosures = ctx.get("disclosures", [])
        trade_stats = ctx.get("trade_stats", {})
        recent_research = ctx.get("recent_research", [])

        if not news and not disclosures:
            return None

        # AI에게 리서치 주제와 수집된 정보를 주고 분석 요청
        news_text = "\n".join(f"- [{n['source']}] {n['title']}" for n in news[:15])
        disc_text = "\n".join(f"- [공시] {d['title']}" for d in disclosures[:10])
        recent_text = "\n".join(f"- {r}" for r in recent_research[:5])

        trade_text = "없음"
        if trade_stats.get("recent_7d"):
            lines = []
            for code, s in trade_stats["recent_7d"].items():
                lines.append(f"  {s['name']}({code}): 매수 {s['buys']}회, 매도 {s['sells']}회")
            trade_text = "\n".join(lines[:10])

        topic_descriptions = {
            "sector_rotation": "섹터 로테이션: 어떤 섹터가 주도주로 부상하고 있는지, 자금 흐름은 어떤지 분석",
            "macro_outlook": "매크로 전망: 금리, 환율, 글로벌 경제 동향이 국내 시장에 미치는 영향",
            "earnings_analysis": "실적/공시 분석: 주요 종목의 실적 전망, 공시 내용의 투자 시사점",
            "theme_discovery": "테마 발굴: 새롭게 부상하는 투자 테마, 관련 수혜주 분석",
            "risk_assessment": "리스크 점검: 현재 시장의 주요 리스크 요인과 대비 전략",
            "portfolio_review": "포트폴리오 최적화: 현재 매매 패턴 기반 개선 제안",
        }
        topic_desc = topic_descriptions.get(topic, topic)

        prompt = f"""당신은 전문 투자 리서치 애널리스트입니다.
아래 정보를 바탕으로 **{topic_desc}**에 대한 심층 분석 리포트를 작성하세요.

## 수집된 뉴스
{news_text if news_text else "없음"}

## 오늘의 공시
{disc_text if disc_text else "없음"}

## 최근 7일 매매 현황 (실제 에이전트 매매)
{trade_text}

## 최근 작성한 리서치 (중복 주의)
{recent_text if recent_text else "없음"}

## 분석 요청
1. 핵심 인사이트 3~5개 (데이터 기반, 구체적)
2. 단기 전략 제안 (1~3일)
3. 중장기 전략 제안 (1주~1개월)
4. 주의해야 할 리스크
5. 관심 종목 추천/비추천 (근거 포함)

## 응답 (JSON만)
{{"title": "리포트 제목",
  "insights": ["인사이트1", "인사이트2", ...],
  "short_term": {{"strategy": "단기 전략 설명", "picks": [{{"code": "종목코드", "name": "종목명", "action": "매수/매도/관망", "reason": "근거"}}]}},
  "mid_term": {{"strategy": "중장기 전략 설명", "themes": ["테마1", ...]}},
  "risks": ["리스크1", ...],
  "summary": "전체 요약 2~3줄"}}"""

        try:
            resp = await self.ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            analysis = json.loads(text)
            analysis["topic"] = topic
            analysis["raw"] = text
            return {"type": "research_report", "analysis": analysis}

        except json.JSONDecodeError:
            logger.warning("[research] 분석 JSON 파싱 실패")
            return None
        except Exception as e:
            logger.error(f"[research] AI 분석 오류: {e}")
            return None

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("type") != "research_report":
            return

        analysis = decision.get("analysis", {})
        title = analysis.get("title", "투자 리서치")
        topic = analysis.get("topic", "")
        insights = analysis.get("insights", [])
        short_term = analysis.get("short_term", {})
        mid_term = analysis.get("mid_term", {})
        risks = analysis.get("risks", [])
        summary = analysis.get("summary", "")

        # 1) 슬랙 보고
        lines = [
            f"🔬 *[투자 리서치] {title}*",
            f"_{summary}_",
            "",
        ]
        if insights:
            lines.append("*핵심 인사이트:*")
            for i, ins in enumerate(insights[:5], 1):
                lines.append(f"  {i}. {ins}")

        if short_term.get("picks"):
            lines.append("\n*단기 종목 의견:*")
            for p in short_term["picks"][:5]:
                emoji = {"매수": "🟢", "매도": "🔴", "관망": "⚪"}.get(p.get("action", ""), "⚪")
                name = p.get("name", WATCH_STOCKS.get(p.get("code", ""), p.get("code", "")))
                lines.append(f"  {emoji} {name}: {p.get('action','')} - {p.get('reason','')}")

        if risks:
            lines.append(f"\n⚠️ *리스크*: {' / '.join(risks[:3])}")

        await self.say("\n".join(lines), self.CHANNEL)

        # 2) Supabase 저장 (매매 에이전트가 참조)
        try:
            self.supabase.table("collected_items").insert({
                "hash": f"research_{self._now().strftime('%Y%m%d_%H')}_{topic}",
                "title": f"[리서치] {title}",
                "content": json.dumps(analysis, ensure_ascii=False),
                "source": "invest_research",
                "source_type": "research",
            }).execute()
        except Exception as e:
            logger.warning(f"[research] Supabase 저장 실패: {e}")

        # 3) 노션 저장 (AI 에이전트 결과물 DB)
        try:
            notion_db_id = os.environ.get(
                "NOTION_AGENT_RESULTS_DB_ID",
                "1e21114e-6491-8101-8b67-ca52d78a8fb0",
            )
            if self.notion:
                from integrations.notion_client import NotionClient
                # 본문 구성
                blocks = [
                    NotionClient.block_heading(title),
                    NotionClient.block_paragraph(summary),
                    NotionClient.block_divider(),
                ]

                if insights:
                    blocks.append(NotionClient.block_heading("핵심 인사이트", level=2))
                    for ins in insights:
                        blocks.append(NotionClient.block_paragraph(f"• {ins}"))

                if short_term:
                    blocks.append(NotionClient.block_heading("단기 전략", level=2))
                    blocks.append(NotionClient.block_paragraph(short_term.get("strategy", "")))
                    for p in short_term.get("picks", []):
                        name = p.get("name", "")
                        blocks.append(NotionClient.block_paragraph(
                            f"→ {name}: {p.get('action','')} - {p.get('reason','')}"
                        ))

                if mid_term:
                    blocks.append(NotionClient.block_heading("중장기 전략", level=2))
                    blocks.append(NotionClient.block_paragraph(mid_term.get("strategy", "")))

                if risks:
                    blocks.append(NotionClient.block_heading("리스크", level=2))
                    for r in risks:
                        blocks.append(NotionClient.block_paragraph(f"⚠️ {r}"))

                await self.notion.create_page(
                    database_id=notion_db_id,
                    properties={
                        "이름": NotionClient.prop_title(
                            f"[투자리서치] {self._now().strftime('%m/%d')} {title}"
                        ),
                    },
                    content_blocks=blocks,
                )
                logger.info(f"[research] 노션 저장 완료: {title}")
        except Exception as e:
            logger.warning(f"[research] 노션 저장 실패: {e}")

        logger.info(f"[research] 리서치 완료: {title} ({topic})")

    # ── 정리 ───────────────────────────────────────────

    async def cleanup(self):
        await self._http.aclose()
