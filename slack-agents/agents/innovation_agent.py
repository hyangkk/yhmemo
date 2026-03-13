"""
혁신 사업개발 에이전트 (Innovation Business Development Agent)

역할:
- 6시간마다(1시, 7시, 13시, 19시) 혁신 사업 아이템을 리서치하여 슬랙에 보고
- 성공 사례, 트렌드 기반 공통 니즈, AI 네이티브 재혁신(뷰자데), 전문성 확장 등 다각도 접근
- 매번 다른 관점/도메인에서 새로운 인사이트를 발굴

관점 프레임워크:
1. 성공 사례 분석: 최근 성공한 스타트업/서비스에서 패턴 추출
2. 트렌드 교차점: 여러 트렌드의 공통 니즈를 해결하는 사업 기회
3. 뷰자데(Vuja De): 익숙한 기존 사업을 AI 네이티브로 완전 재혁신
4. 전문성 디벨롭: 기존 역량(AI, 개발, 투자)을 확장하는 사업 기회
"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta

import aiohttp
import feedparser
from urllib.parse import quote

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
INNOVATION_HISTORY_FILE = os.path.join(DATA_DIR, "innovation_history.json")

# 리서치 관점 프레임워크
PERSPECTIVES = [
    {
        "id": "success_case",
        "name": "성공 사례 해부",
        "description": "최근 급성장한 스타트업/서비스의 핵심 성공 요인을 분석하고, 유사하게 적용 가능한 사업 기회 도출",
        "search_queries": [
            "AI startup funding 2025 2026",
            "fastest growing SaaS startups",
            "YC top companies recent batch",
            "successful solo founder startup",
            "bootstrapped profitable startup",
            "one person billion dollar company AI",
        ],
    },
    {
        "id": "trend_intersection",
        "name": "트렌드 교차점",
        "description": "여러 메가트렌드가 교차하는 지점에서 아직 해결되지 않은 공통 니즈를 발견",
        "search_queries": [
            "AI agent market opportunity 2026",
            "vertical AI SaaS trends",
            "emerging technology convergence business",
            "underserved market AI automation",
            "B2B AI workflow automation trend",
            "AI native product replacing legacy software",
        ],
    },
    {
        "id": "vuja_de",
        "name": "뷰자데 재혁신",
        "description": "너무 익숙해서 당연하게 여기는 기존 사업/서비스를 AI 네이티브 관점으로 완전히 다시 상상",
        "search_queries": [
            "AI disrupting traditional industry",
            "AI replacing entire workflow not just feature",
            "rethinking everyday software with AI",
            "AI first company reimagining legacy business",
            "zero to one AI product innovation",
            "industry ripe for AI disruption",
        ],
    },
    {
        "id": "expertise_expand",
        "name": "전문성 확장",
        "description": "AI/개발/투자 역량을 기반으로 인접 도메인에서 독보적 경쟁력을 가질 수 있는 사업 기회",
        "search_queries": [
            "developer tools AI startup ideas",
            "AI agent platform business model",
            "fintech AI automation opportunity",
            "technical founder competitive advantage",
            "AI consulting productized service",
            "open source AI monetization strategy",
        ],
    },
]

# Google News RSS 기반 뉴스 수집 쿼리
NEWS_QUERIES = [
    "AI startup funding",
    "AI native business model",
    "vertical AI SaaS",
    "one person company AI",
    "AI agent business",
    "innovative business model 2026",
    "AI replacing SaaS",
    "solo founder AI startup",
    "AI workflow automation business",
    "disruptive AI company",
]


class InnovationAgent(BaseAgent):
    """6시간마다 혁신 사업 아이템을 리서치하여 슬랙에 보고하는 에이전트"""

    def __init__(self, target_channel: str = "C0AJJ469SV8", **kwargs):  # ai-agents-general
        super().__init__(
            name="innovation",
            description="6시간마다 혁신 사업 아이템을 리서치하여 보고. 성공 사례, 트렌드 교차점, 뷰자데 재혁신, 전문성 확장 등 다각도 접근",
            slack_channel=target_channel,
            loop_interval=60,  # 1분마다 체크 (정각에만 실행)
            **kwargs,
        )
        self._target_channel = target_channel
        self._last_sent_slot: str | None = None
        self._history: list[dict] = self._load_history()
        self._perspective_index = 0  # 관점 순환 인덱스

    # ── 이력 관리 ──────────────────────────────────────

    def _load_history(self) -> list[dict]:
        try:
            with open(INNOVATION_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._history = self._history[-200:]
        with open(INNOVATION_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._history, ensure_ascii=False, indent=2))

    def _get_recent_topics(self) -> list[str]:
        """최근 7일간 다룬 주제 (중복 방지)"""
        cutoff = (datetime.now(KST) - timedelta(days=7)).isoformat()
        return [
            h.get("title", "")
            for h in self._history
            if h.get("sent_at", "") >= cutoff
        ]

    def _next_perspective(self) -> dict:
        """관점을 순환하며 선택"""
        perspective = PERSPECTIVES[self._perspective_index % len(PERSPECTIVES)]
        self._perspective_index += 1
        return perspective

    # ── 웹 리서치 ──────────────────────────────────────

    async def _search_web(self, query: str) -> str:
        """DuckDuckGo로 웹 검색"""
        from core.tools import _web_search
        try:
            return await _web_search(query)
        except Exception as e:
            logger.warning(f"[innovation] Web search failed for '{query}': {e}")
            return ""

    async def _fetch_news(self, query: str) -> list[dict]:
        """Google News RSS로 관련 뉴스 수집"""
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=US&ceid=US:en"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        feed = feedparser.parse(text)
                        return [
                            {"title": e.get("title", ""), "link": e.get("link", ""), "published": e.get("published", "")}
                            for e in feed.entries[:5]
                        ]
        except Exception as e:
            logger.warning(f"[innovation] News fetch failed for '{query}': {e}")
        return []

    async def _gather_research(self, perspective: dict) -> dict:
        """특정 관점에서 리서치 데이터 수집"""
        # 검색 쿼리 중 2~3개 랜덤 선택
        queries = random.sample(perspective["search_queries"], min(3, len(perspective["search_queries"])))

        # 뉴스 쿼리 1~2개 랜덤 선택
        news_queries = random.sample(NEWS_QUERIES, 2)

        # 병렬로 웹 검색 + 뉴스 수집
        search_tasks = [self._search_web(q) for q in queries]
        news_tasks = [self._fetch_news(q) for q in news_queries]

        results = await asyncio.gather(*search_tasks, *news_tasks, return_exceptions=True)

        search_results = []
        for i, r in enumerate(results[:len(queries)]):
            if isinstance(r, str) and r.strip():
                search_results.append(f"[검색: {queries[i]}]\n{r[:1500]}")

        news_articles = []
        for i, r in enumerate(results[len(queries):]):
            if isinstance(r, list):
                for article in r:
                    news_articles.append(f"- {article['title']}")

        return {
            "perspective": perspective,
            "search_results": "\n\n".join(search_results) if search_results else "(검색 결과 없음)",
            "news_headlines": "\n".join(news_articles[:10]) if news_articles else "(뉴스 없음)",
        }

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        current_hour = now.hour

        # 6시간마다 정각(0~5분)에 실행 (1시, 7시, 13시, 19시)
        if 0 <= now.minute <= 5 and current_hour % 6 == 1:
            current_slot = f"{current_hour}:00"
        else:
            return None

        # 이미 이번 슬롯에 보냈으면 스킵
        if self._last_sent_slot == current_slot:
            return None

        logger.info(f"[innovation] Starting research cycle at {now.strftime('%H:%M')}")

        # 이번에 사용할 관점 선택
        perspective = self._next_perspective()

        # 리서치 데이터 수집
        research = await self._gather_research(perspective)

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": current_hour,
            "perspective": perspective,
            "search_results": research["search_results"],
            "news_headlines": research["news_headlines"],
            "recent_topics": self._get_recent_topics(),
        }

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        perspective = context["perspective"]
        recent_topics = context.get("recent_topics", [])
        recent_text = "\n".join(f"- {t}" for t in recent_topics) if recent_topics else "(아직 없음)"

        system_prompt = f"""당신은 혁신 사업개발 전문가입니다. 사용자에게 실행 가능한 혁신 사업 아이템을 제안합니다.

오늘의 분석 관점: [{perspective['name']}]
{perspective['description']}

분석 원칙:
1. **접근성**: 1인 또는 소규모 팀이 시작할 수 있는 현실적인 아이템
2. **AI 네이티브**: 단순 AI 기능 추가가 아닌, AI 없이는 불가능한 근본적 혁신
3. **구체성**: "AI로 뭔가 하자" 수준이 아닌, 타겟 고객/문제/솔루션이 명확한 제안
4. **독창성**: 이미 레드오션인 영역이 아닌, 블루오션 또는 차별화 가능한 각도
5. **뷰자데**: 익숙한 것을 낯설게 보기 — 기존 방식을 당연하게 여기지 말 것

사용자 프로필:
- AI/개발 전문성 보유 (슬랙 봇, 에이전트 시스템 등 구축 경험)
- 투자/트레이딩에 관심
- 1인 또는 소규모로 빠르게 실행 가능한 것 선호
- 한국 시장 + 글로벌 시장 모두 관심

출력 형식 (반드시 JSON):
{{
  "title": "사업 아이템 한 줄 제목 (30자 이내)",
  "problem": "해결하려는 핵심 문제 (2~3문장)",
  "solution": "AI 네이티브 솔루션 설명 (3~4문장)",
  "why_now": "왜 지금이 적기인지 (1~2문장)",
  "market": "타겟 시장과 규모 추정 (1~2문장)",
  "competitive_edge": "경쟁 우위/차별점 (1~2문장)",
  "first_step": "지금 바로 시작할 수 있는 첫 번째 액션 (구체적으로)",
  "reference": "참고한 사례나 트렌드 (1줄)",
  "excitement_score": 1~10 사이 정수 (얼마나 흥분되는 아이템인지)
}}"""

        user_prompt = f"""리서치 데이터:

{context['search_results']}

최근 관련 뉴스:
{context['news_headlines']}

최근 7일간 이미 다룬 주제 (중복 금지):
{recent_text}

위 데이터를 바탕으로 [{perspective['name']}] 관점에서 실행 가능한 혁신 사업 아이템 1개를 제안해주세요.
이미 다룬 주제와 겹치지 않는, 새로운 각도의 아이템을 제시해야 합니다."""

        result_text = await self.ai_think(
            system_prompt, user_prompt,
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
        )

        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean.strip())
        except json.JSONDecodeError:
            logger.error(f"[innovation] Failed to parse AI response: {result_text[:200]}")
            return None

        title = parsed.get("title", "").strip()
        if not title:
            return None

        return {
            "action": "send_innovation_report",
            "perspective": perspective,
            "title": title,
            "problem": parsed.get("problem", ""),
            "solution": parsed.get("solution", ""),
            "why_now": parsed.get("why_now", ""),
            "market": parsed.get("market", ""),
            "competitive_edge": parsed.get("competitive_edge", ""),
            "first_step": parsed.get("first_step", ""),
            "reference": parsed.get("reference", ""),
            "excitement_score": parsed.get("excitement_score", 5),
            "hour": context["current_hour"],
        }

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        if decision.get("action") != "send_innovation_report":
            return

        message = self._format_message(decision)
        await self._reply(self._target_channel, message)
        logger.info(f"[innovation] Sent report: {decision['title']}")

        # 전송 완료 표시
        now = datetime.now(KST)
        self._last_sent_slot = f"{now.hour}:00"

        # 이력 저장
        self._history.append({
            "title": decision["title"],
            "perspective": decision["perspective"]["id"],
            "excitement_score": decision.get("excitement_score", 5),
            "sent_at": now.isoformat(),
        })
        self._save_history()

    # ── 수동 실행 ────────────────────────────────────────

    async def run_once(self, channel: str = None, thread_ts: str = None, topic: str = None):
        """수동 실행: !혁신 명령어로 즉시 사업 아이템 리서치"""
        logger.info(f"[innovation] Manual run requested, topic={topic}")

        # 관점 선택 (주제가 있으면 관련 관점, 없으면 순환)
        if topic:
            perspective = self._match_perspective(topic)
        else:
            perspective = self._next_perspective()

        # 주제가 있으면 검색 쿼리 오버라이드
        if topic:
            perspective = {**perspective, "search_queries": [
                f"{topic} AI startup",
                f"{topic} business opportunity 2026",
                f"{topic} innovation trend",
            ]}

        research = await self._gather_research(perspective)

        context = {
            "current_time": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "current_hour": datetime.now(KST).hour,
            "perspective": perspective,
            "search_results": research["search_results"],
            "news_headlines": research["news_headlines"],
            "recent_topics": self._get_recent_topics(),
        }

        decision = await self.think(context)
        if not decision:
            return "리서치 결과를 분석하지 못했어요. 다시 시도해주세요."

        message = self._format_message(decision)
        target = channel or self._target_channel
        await self._reply(target, message, thread_ts=thread_ts)

        self._history.append({
            "title": decision["title"],
            "perspective": decision["perspective"]["id"],
            "excitement_score": decision.get("excitement_score", 5),
            "sent_at": datetime.now(KST).isoformat(),
        })
        self._save_history()
        return None  # 성공

    def _match_perspective(self, topic: str) -> dict:
        """주제에 가장 잘 맞는 관점 선택"""
        topic_lower = topic.lower()
        if any(k in topic_lower for k in ["성공", "사례", "유니콘", "스타트업"]):
            return PERSPECTIVES[0]
        elif any(k in topic_lower for k in ["트렌드", "니즈", "시장"]):
            return PERSPECTIVES[1]
        elif any(k in topic_lower for k in ["뷰자데", "재혁신", "레거시", "기존"]):
            return PERSPECTIVES[2]
        elif any(k in topic_lower for k in ["전문", "역량", "개발", "투자"]):
            return PERSPECTIVES[3]
        return random.choice(PERSPECTIVES)

    def _format_message(self, decision: dict) -> str:
        """슬랙 메시지 포맷"""
        perspective = decision.get("perspective", {})
        perspective_name = perspective.get("name", "")
        title = decision.get("title", "")
        problem = decision.get("problem", "")
        solution = decision.get("solution", "")
        why_now = decision.get("why_now", "")
        market = decision.get("market", "")
        competitive_edge = decision.get("competitive_edge", "")
        first_step = decision.get("first_step", "")
        reference = decision.get("reference", "")
        excitement = decision.get("excitement_score", 5)

        # 관점 이모지
        perspective_emoji = {
            "success_case": "🏆",
            "trend_intersection": "🔀",
            "vuja_de": "🔮",
            "expertise_expand": "🚀",
        }.get(perspective.get("id", ""), "💡")

        # 흥분도 바
        excitement_bar = "🔥" * min(excitement, 10) + "⬜" * max(0, 10 - excitement)

        msg = f"{perspective_emoji} *혁신 사업 아이템 — {perspective_name}*\n\n"
        msg += f"*💡 {title}*\n\n"
        msg += f"*🎯 문제:*\n{problem}\n\n"
        msg += f"*🛠️ 솔루션:*\n{solution}\n\n"
        msg += f"*⏰ 왜 지금:*\n{why_now}\n\n"
        msg += f"*📊 시장:*\n{market}\n\n"
        msg += f"*⚔️ 경쟁 우위:*\n{competitive_edge}\n\n"
        msg += f"*👣 첫 번째 액션:*\n{first_step}\n\n"
        if reference:
            msg += f"*📎 참고:* {reference}\n\n"
        msg += f"*흥분도:* {excitement_bar} ({excitement}/10)\n\n"
        msg += "`⏰ 6시간마다 자동 발송 | !혁신 [주제]로 즉시 실행`"

        return msg
