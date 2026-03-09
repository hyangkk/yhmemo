"""
소셜 센티멘트 분석 에이전트 (Social Sentiment Agent)

역할:
- Reddit(r/cryptocurrency, r/wallstreetbets 등) 커뮤니티 글 수집
- CryptoPanic 뉴스 감성 데이터 수집
- Claude AI로 종합 감성 분석 및 트렌드 파악
- 매일 아침/저녁 센티멘트 브리핑 + 급변 시 알림
- Supabase에 히스토리 저장

채널: #ai-invest
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
SENTIMENT_STATE_FILE = os.path.join(DATA_DIR, "sentiment_state.json")
SENTIMENT_HISTORY_FILE = os.path.join(DATA_DIR, "sentiment_history.json")

# Reddit 서브레딧 목록
SUBREDDITS = [
    "cryptocurrency",
    "Bitcoin",
    "ethereum",
    "wallstreetbets",
    "stocks",
    "CryptoMarkets",
]

# 관심 키워드 (감성 추적 대상)
WATCH_KEYWORDS = {
    "BTC": ["bitcoin", "btc", "비트코인"],
    "ETH": ["ethereum", "eth", "이더리움"],
    "SOL": ["solana", "sol", "솔라나"],
    "XRP": ["ripple", "xrp", "리플"],
    "AI/반도체": ["nvidia", "nvda", "ai stocks", "반도체", "semiconductor"],
    "금/원자재": ["gold", "paxg", "commodity", "금"],
    "전체시장": ["market crash", "bull run", "bear market", "recession", "rally"],
}

# 센티멘트 브리핑 시각 (KST)
BRIEFING_HOURS = [8, 20]

# 급변 알림 기준 (이전 대비 점수 변화)
SENTIMENT_ALERT_THRESHOLD = 25  # 100점 만점 기준 25점 이상 변화


class SentimentAgent(BaseAgent):
    """소셜 커뮤니티 감성 분석 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, target_channel: str = "ai-invest", **kwargs):
        super().__init__(
            name="sentiment",
            description="Reddit/뉴스 소셜 센티멘트 수집·분석 에이전트 (X, Reddit 커뮤니티 감성 분석)",
            slack_channel=target_channel,
            loop_interval=int(os.environ.get("SENTIMENT_INTERVAL", 1800)),  # 30분
            **kwargs,
        )
        self._target_channel = target_channel
        self._ensure_table()
        self._state = self._load_state()
        self._last_briefing_hour: int | None = self._state.get("last_briefing_hour")
        self._last_scores: dict = self._state.get("last_scores", {})
        self._history = self._load_history()
        self._seen_hashes: set = set(self._state.get("seen_hashes", []))

    # ── 테이블 자동 생성 ────────────────────────────────

    def _ensure_table(self):
        """Supabase에 social_sentiment 테이블이 없으면 psycopg2로 직접 생성"""
        try:
            if not self.supabase:
                return
            self.supabase.table("social_sentiment").select("id").limit(1).execute()
            logger.info("[sentiment] social_sentiment table exists")
        except Exception:
            logger.info("[sentiment] social_sentiment table not found, creating via psycopg2...")
            try:
                import psycopg2

                supabase_url = os.environ.get("SUPABASE_URL", "")
                service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
                ref = supabase_url.replace("https://", "").split(".")[0] if supabase_url else ""

                if not ref or not service_key:
                    logger.warning("[sentiment] Missing SUPABASE_URL or SERVICE_ROLE_KEY for table creation")
                    return

                conn = psycopg2.connect(
                    host="aws-0-ap-northeast-1.pooler.supabase.com",
                    port=5432,
                    dbname="postgres",
                    user=f"postgres.{ref}",
                    password=service_key,
                    sslmode="require",
                    connect_timeout=15,
                )
                conn.autocommit = True
                cur = conn.cursor()

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS social_sentiment (
                        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                        overall_score int NOT NULL CHECK (overall_score BETWEEN 0 AND 100),
                        overall_label text NOT NULL DEFAULT '중립',
                        asset_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
                        trending_topics text[] DEFAULT ARRAY[]::text[],
                        summary text,
                        risk_alert text,
                        source_feeds jsonb DEFAULT '{}'::jsonb,
                        bullish_signals text[] DEFAULT ARRAY[]::text[],
                        bearish_signals text[] DEFAULT ARRAY[]::text[],
                        analyzed_at timestamptz NOT NULL DEFAULT now(),
                        created_at timestamptz NOT NULL DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_social_sentiment_analyzed_at
                        ON social_sentiment (analyzed_at DESC);
                """)
                cur.execute("ALTER TABLE social_sentiment ENABLE ROW LEVEL SECURITY;")
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_policies
                            WHERE tablename = 'social_sentiment'
                            AND policyname = 'Service role full access'
                        ) THEN
                            CREATE POLICY "Service role full access" ON social_sentiment
                                FOR ALL USING (true) WITH CHECK (true);
                        END IF;
                    END $$;
                """)

                cur.close()
                conn.close()
                logger.info("[sentiment] Created social_sentiment table via psycopg2")

                import time
                time.sleep(2)

            except Exception as e2:
                logger.warning(f"[sentiment] Table auto-create failed: {e2}")

    # ── 상태 관리 ──────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(SENTIMENT_STATE_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        state = {
            "last_briefing_hour": self._last_briefing_hour,
            "last_scores": self._last_scores,
            "seen_hashes": list(self._seen_hashes)[-500:],
            "updated_at": datetime.now(KST).isoformat(),
        }
        with open(SENTIMENT_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, ensure_ascii=False, indent=2))

    def _load_history(self) -> list:
        try:
            with open(SENTIMENT_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save_history(self, entry: dict):
        self._history.append(entry)
        self._history = self._history[-200:]  # 최근 200건
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SENTIMENT_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._history, ensure_ascii=False, indent=2))

    # ── Observe: 소셜 데이터 수집 ─────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "reddit_posts": [],
            "crypto_news": [],
            "alerts": [],
        }

        # 1. Reddit 데이터 수집
        try:
            reddit_posts = await self._fetch_reddit_posts()
            context["reddit_posts"] = reddit_posts
            logger.info(f"[sentiment] Reddit: {len(reddit_posts)} posts collected")
        except Exception as e:
            logger.error(f"[sentiment] Reddit fetch error: {e}")

        # 2. CryptoPanic 뉴스 수집
        try:
            crypto_news = await self._fetch_crypto_news()
            context["crypto_news"] = crypto_news
            logger.info(f"[sentiment] CryptoPanic: {len(crypto_news)} articles collected")
        except Exception as e:
            logger.debug(f"[sentiment] CryptoPanic fetch error: {e}")

        # 수집된 데이터가 없으면 스킵
        if not context["reddit_posts"] and not context["crypto_news"]:
            logger.warning("[sentiment] No social data collected, skipping cycle")
            return None

        # 3. 브리핑 시간 체크
        context["is_briefing_time"] = (
            now.hour in BRIEFING_HOURS and self._last_briefing_hour != now.hour
        )

        return context

    # ── Think: AI 감성 분석 ────────────────────────────

    async def think(self, context: dict) -> dict | None:
        reddit_posts = context.get("reddit_posts", [])
        crypto_news = context.get("crypto_news", [])

        # 소셜 데이터를 텍스트로 정리
        social_text = self._compile_social_text(reddit_posts, crypto_news)
        if not social_text.strip():
            return None

        # AI로 감성 분석
        try:
            analysis = await self._analyze_sentiment(social_text)
        except Exception as e:
            logger.error(f"[sentiment] AI analysis error: {e}")
            return None

        if not analysis:
            return None

        # 점수 변화 감지 (급변 알림)
        alerts = []
        new_scores = analysis.get("scores", {})
        for asset, score in new_scores.items():
            old_score = self._last_scores.get(asset, 50)  # 기본 50 (중립)
            change = score - old_score
            if abs(change) >= SENTIMENT_ALERT_THRESHOLD:
                alerts.append({
                    "asset": asset,
                    "old_score": old_score,
                    "new_score": score,
                    "change": change,
                })

        actions = []

        # 항상 분석 결과 저장 (원본 글 포함)
        actions.append({
            "type": "save",
            "data": analysis,
            "reddit_posts": reddit_posts,
            "crypto_news": crypto_news,
        })

        # 급변 알림
        if alerts:
            actions.append({"type": "alert", "data": alerts, "analysis": analysis})

        # 정시 브리핑
        if context.get("is_briefing_time"):
            actions.append({
                "type": "briefing",
                "data": analysis,
                "hour": context["current_hour"],
            })

        return {"actions": actions, "analysis": analysis, "context": context}

    # ── Act: 결과 전송 ─────────────────────────────────

    async def act(self, decision: dict):
        analysis = decision.get("analysis", {})
        context = decision.get("context", {})

        for action in decision.get("actions", []):
            try:
                if action["type"] == "save":
                    await self._save_analysis(
                        action["data"],
                        reddit_posts=action.get("reddit_posts", []),
                        crypto_news=action.get("crypto_news", []),
                    )
                elif action["type"] == "alert":
                    await self._send_sentiment_alert(action["data"], action["analysis"])
                elif action["type"] == "briefing":
                    await self._send_sentiment_briefing(action["data"], action["hour"])
            except Exception as e:
                logger.error(f"[sentiment] Act error ({action['type']}): {e}")

        # 상태 업데이트
        self._last_scores = analysis.get("scores", {})
        if context.get("is_briefing_time"):
            self._last_briefing_hour = context["current_hour"]
        self._save_state()

    # ── 데이터 수집 ───────────────────────────────────

    async def _fetch_reddit_posts(self) -> list[dict]:
        """Reddit에서 인기 게시물 수집 (공개 JSON API 사용)"""
        posts = []
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "YHMemo-SentimentBot/1.0"},
            follow_redirects=True,
        ) as client:
            tasks = [
                self._fetch_subreddit(client, sub) for sub in SUBREDDITS
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, list):
                    posts.extend(result)

        # 중복 제거
        unique = []
        for p in posts:
            h = hashlib.md5(p["title"].encode()).hexdigest()[:12]
            if h not in self._seen_hashes:
                self._seen_hashes.add(h)
                unique.append(p)

        # 점수 기준 상위 30개
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)
        return unique[:30]

    async def _fetch_subreddit(self, client: httpx.AsyncClient, subreddit: str) -> list[dict]:
        """단일 서브레딧에서 핫 게시물 가져오기 (Reddit JSON → Pullpush 백업)"""
        # 1차: Reddit 공식 JSON API
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=15"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                posts = []
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    if post.get("stickied"):
                        continue
                    posts.append({
                        "source": f"r/{subreddit}",
                        "title": post.get("title", ""),
                        "selftext": (post.get("selftext", "") or "")[:300],
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "upvote_ratio": post.get("upvote_ratio", 0),
                        "created_utc": post.get("created_utc", 0),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                    })
                if posts:
                    return posts
                logger.debug(f"[sentiment] Reddit r/{subreddit}: empty response, trying Pullpush")
            else:
                logger.debug(f"[sentiment] Reddit r/{subreddit}: HTTP {resp.status_code}, trying Pullpush")
        except Exception as e:
            logger.debug(f"[sentiment] Reddit r/{subreddit} error: {e}, trying Pullpush")

        # 2차: Pullpush API (Reddit 아카이브, 403 차단 시 백업)
        try:
            pp_url = f"https://api.pullpush.io/reddit/search/submission/?subreddit={subreddit}&sort=score&sort_type=desc&size=15&after=24h"
            resp = await client.get(pp_url, timeout=httpx.Timeout(20.0))
            if resp.status_code == 200:
                data = resp.json()
                posts = []
                for post in data.get("data", []):
                    posts.append({
                        "source": f"r/{subreddit}",
                        "title": post.get("title", ""),
                        "selftext": (post.get("selftext", "") or "")[:300],
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "upvote_ratio": post.get("upvote_ratio", 0),
                        "created_utc": post.get("created_utc", 0),
                        "url": f"https://reddit.com/r/{subreddit}/comments/{post.get('id', '')}",
                    })
                logger.info(f"[sentiment] Pullpush r/{subreddit}: {len(posts)} posts")
                return posts
        except Exception as e:
            logger.debug(f"[sentiment] Pullpush r/{subreddit} error: {e}")

        return []

    async def _fetch_crypto_news(self) -> list[dict]:
        """CryptoPanic 무료 API로 뉴스 수집"""
        articles = []
        # CryptoPanic public feed (무료, API 키 불필요)
        url = "https://cryptopanic.com/api/free/v1/posts/?auth_token=free&public=true&kind=news"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("results", [])[:20]:
                        articles.append({
                            "source": "CryptoPanic",
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "votes": item.get("votes", {}),
                            "sentiment": item.get("sentiment", ""),
                            "published_at": item.get("published_at", ""),
                        })
        except Exception as e:
            logger.debug(f"[sentiment] CryptoPanic error: {e}")

        return articles

    # ── AI 분석 ────────────────────────────────────────

    def _compile_social_text(self, reddit_posts: list, crypto_news: list) -> str:
        """수집된 데이터를 분석용 텍스트로 정리"""
        lines = []

        if reddit_posts:
            lines.append("=== Reddit 인기 게시물 ===")
            for p in reddit_posts[:20]:
                score_str = f"(↑{p['score']}, 댓글{p['num_comments']})"
                lines.append(f"[{p['source']}] {p['title']} {score_str}")
                if p.get("selftext"):
                    lines.append(f"  → {p['selftext'][:150]}")

        if crypto_news:
            lines.append("\n=== 암호화폐 뉴스 ===")
            for n in crypto_news[:15]:
                sentiment_tag = ""
                if n.get("votes"):
                    pos = n["votes"].get("positive", 0)
                    neg = n["votes"].get("negative", 0)
                    sentiment_tag = f" [👍{pos}/👎{neg}]"
                lines.append(f"[{n['source']}] {n['title']}{sentiment_tag}")

        return "\n".join(lines)

    async def _analyze_sentiment(self, social_text: str) -> dict | None:
        """Claude AI로 종합 감성 분석"""
        prompt = f"""다음은 최근 Reddit 커뮤니티와 암호화폐 뉴스에서 수집한 소셜 데이터입니다.

{social_text}

위 데이터를 분석하여 아래 JSON 형식으로 응답하세요:

{{
  "overall_score": <0-100 정수, 0=극도공포, 50=중립, 100=극도탐욕>,
  "overall_label": "<극도 공포|공포|약한 공포|중립|약한 낙관|낙관|극도 탐욕>",
  "scores": {{
    "BTC": <0-100>,
    "ETH": <0-100>,
    "SOL": <0-100>,
    "XRP": <0-100>,
    "AI/반도체": <0-100>,
    "전체시장": <0-100>
  }},
  "trending_topics": ["<상위 5개 핫토픽>"],
  "bullish_signals": ["<강세 시그널 3개>"],
  "bearish_signals": ["<약세 시그널 3개>"],
  "summary": "<3-4문장으로 현재 소셜 센티멘트 요약. 한국어로 작성.>",
  "risk_alert": "<있으면 위험 경고 1줄, 없으면 빈 문자열>",
  "platform_summaries": {{
    "reddit": "<Reddit 커뮤니티의 총체적 분위기를 2-3문장으로 요약. 주요 논의 주제, 감성 경향 등. 한국어.>",
    "news": "<뉴스 매체의 총체적 분위기를 2-3문장으로 요약. 주요 헤드라인 트렌드 등. 한국어.>"
  }}
}}

중요:
- Reddit 게시물의 upvote 수와 댓글 수가 많을수록 영향력 큼
- 뉴스의 긍정/부정 투표도 반영
- 커뮤니티의 전반적 분위기(FOMO, FUD, 관망 등) 파악
- 반드시 유효한 JSON만 출력"""

        try:
            response = await self.ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
                system="당신은 금융 소셜 미디어 감성 분석 전문가입니다. 커뮤니티 데이터를 정량적으로 분석합니다. 반드시 JSON만 출력하세요.",
            )
            text = response.content[0].text.strip()
            # JSON 파싱 (코드블록 제거)
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[sentiment] JSON parse error: {e}")
            return None
        except Exception as e:
            logger.error(f"[sentiment] AI analysis error: {e}")
            return None

    # ── 결과 저장 ──────────────────────────────────────

    async def _save_analysis(self, analysis: dict, reddit_posts: list = None, crypto_news: list = None):
        """분석 결과를 Supabase + 로컬에 저장 (원본 글 포함)"""
        now = datetime.now(KST)
        reddit_posts = reddit_posts or []
        crypto_news = crypto_news or []

        # 원본 글을 채널별로 그룹핑
        source_feeds = {}
        for p in reddit_posts[:20]:
            src = p.get("source", "r/unknown")
            if src not in source_feeds:
                source_feeds[src] = []
            source_feeds[src].append({
                "title": p.get("title", ""),
                "url": p.get("url", ""),
                "score": p.get("score", 0),
                "comments": p.get("num_comments", 0),
                "snippet": (p.get("selftext", "") or "")[:150],
            })
        for n in crypto_news[:15]:
            src = n.get("source", "News")
            if src not in source_feeds:
                source_feeds[src] = []
            source_feeds[src].append({
                "title": n.get("title", ""),
                "url": n.get("url", ""),
                "votes": n.get("votes", {}),
                "sentiment": n.get("sentiment", ""),
            })

        # 플랫폼별 요약을 source_feeds에 포함
        platform_summaries = analysis.get("platform_summaries", {})
        if platform_summaries:
            source_feeds["_platform_summaries"] = platform_summaries

        entry = {
            "timestamp": now.isoformat(),
            "overall_score": analysis.get("overall_score", 50),
            "overall_label": analysis.get("overall_label", "중립"),
            "scores": analysis.get("scores", {}),
            "trending_topics": analysis.get("trending_topics", []),
            "summary": analysis.get("summary", ""),
            "source_feeds": source_feeds,
        }

        # 로컬 저장
        self._save_history(entry)

        # Supabase 저장
        try:
            if self.supabase:
                self.supabase.table("social_sentiment").insert({
                    "overall_score": entry["overall_score"],
                    "overall_label": entry["overall_label"],
                    "asset_scores": json.dumps(entry["scores"], ensure_ascii=False),
                    "trending_topics": entry["trending_topics"],
                    "summary": entry["summary"],
                    "risk_alert": analysis.get("risk_alert", ""),
                    "source_feeds": json.dumps(source_feeds, ensure_ascii=False),
                    "bullish_signals": analysis.get("bullish_signals", []),
                    "bearish_signals": analysis.get("bearish_signals", []),
                    "analyzed_at": now.isoformat(),
                }).execute()
        except Exception as e:
            logger.debug(f"[sentiment] Supabase save error: {e}")

    # ── 알림 전송 ──────────────────────────────────────

    async def _send_sentiment_alert(self, alerts: list, analysis: dict):
        """센티멘트 급변 알림"""
        now = datetime.now(KST)

        for alert in alerts:
            asset = alert["asset"]
            old = alert["old_score"]
            new = alert["new_score"]
            change = alert["change"]

            direction = "급등" if change > 0 else "급락"
            emoji = "🚀" if change > 0 else "🔻"
            bar = self._score_bar(new)

            msg = (
                f"{emoji} *소셜 센티멘트 {direction} 감지!*\n\n"
                f"*{asset}* 센티멘트: {old} → *{new}* ({change:+d}점)\n"
                f"{bar}\n\n"
                f"📝 {analysis.get('summary', '')}\n\n"
                f"_{now.strftime('%H:%M')} KST_"
            )
            await self.say(msg, self._target_channel)

    async def _send_sentiment_briefing(self, analysis: dict, hour: int):
        """정기 센티멘트 브리핑"""
        now = datetime.now(KST)
        greeting = "모닝" if hour < 12 else "이브닝"

        overall = analysis.get("overall_score", 50)
        label = analysis.get("overall_label", "중립")
        scores = analysis.get("scores", {})
        topics = analysis.get("trending_topics", [])
        bullish = analysis.get("bullish_signals", [])
        bearish = analysis.get("bearish_signals", [])
        summary = analysis.get("summary", "")
        risk = analysis.get("risk_alert", "")

        # 전체 센티멘트 바
        overall_bar = self._score_bar(overall)
        overall_emoji = self._score_emoji(overall)

        lines = [
            f"{overall_emoji} *{greeting} 소셜 센티멘트 브리핑* ({now.strftime('%m/%d %H:%M')} KST)",
            "",
            f"*전체 시장 감성:* {label} ({overall}/100)",
            overall_bar,
            "",
        ]

        # 자산별 센티멘트
        if scores:
            lines.append("*자산별 센티멘트:*")
            for asset, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
                bar = self._mini_bar(score)
                emoji = self._score_emoji(score)
                lines.append(f"  {emoji} {asset}: {bar} {score}")
            lines.append("")

        # 트렌딩 토픽
        if topics:
            lines.append("*🔥 핫토픽:*")
            lines.append("  " + " | ".join(f"#{t}" for t in topics[:5]))
            lines.append("")

        # 강세/약세 시그널
        if bullish:
            lines.append("*📈 강세 시그널:*")
            for b in bullish[:3]:
                lines.append(f"  • {b}")
        if bearish:
            lines.append("*📉 약세 시그널:*")
            for b in bearish[:3]:
                lines.append(f"  • {b}")
        lines.append("")

        # 요약
        if summary:
            lines.append(f"*💡 AI 분석:*\n{summary}")

        # 위험 경고
        if risk:
            lines.append(f"\n⚠️ *주의:* {risk}")

        # 히스토리 트렌드 (최근 5건)
        if len(self._history) >= 2:
            recent = self._history[-5:]
            trend_scores = [h["overall_score"] for h in recent]
            trend_line = " → ".join(str(s) for s in trend_scores)
            trend_dir = "↗️" if trend_scores[-1] > trend_scores[0] else ("↘️" if trend_scores[-1] < trend_scores[0] else "➡️")
            lines.append(f"\n*📊 최근 추세:* {trend_line} {trend_dir}")

        lines.append("\n_투자 결정은 본인의 판단으로._")

        await self.say("\n".join(lines), self._target_channel)

    # ── 수동 실행 (슬랙 명령) ──────────────────────────

    async def run_manual(self, channel: str = None, thread_ts: str = None, query: str = None):
        """!센티멘트 명령어로 수동 실행"""
        target = channel or self._target_channel

        # 특정 키워드 검색
        if query:
            return await self._analyze_keyword(query, target, thread_ts)

        # 전체 분석
        context = await self.observe()
        if not context:
            msg = "소셜 데이터 수집에 실패했습니다. 잠시 후 다시 시도해주세요."
            if thread_ts:
                await self.slack.send_thread_reply(target, thread_ts, msg)
            else:
                await self.say(msg, target)
            return

        decision = await self.think(context)
        if decision and decision.get("analysis"):
            analysis = decision["analysis"]
            await self._save_analysis(analysis)
            await self._send_sentiment_briefing(analysis, datetime.now(KST).hour)
            self._last_scores = analysis.get("scores", {})
            self._save_state()
        else:
            msg = "분석 결과를 생성하지 못했습니다."
            if thread_ts:
                await self.slack.send_thread_reply(target, thread_ts, msg)
            else:
                await self.say(msg, target)

    async def _analyze_keyword(self, keyword: str, channel: str, thread_ts: str = None):
        """특정 키워드에 대한 센티멘트 분석"""
        # Reddit 검색
        posts = []
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "YHMemo-SentimentBot/1.0"},
            follow_redirects=True,
        ) as client:
            url = f"https://www.reddit.com/search.json?q={keyword}&sort=relevance&t=day&limit=15"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    for child in data.get("data", {}).get("children", []):
                        post = child.get("data", {})
                        posts.append({
                            "source": f"r/{post.get('subreddit', '?')}",
                            "title": post.get("title", ""),
                            "selftext": (post.get("selftext", "") or "")[:200],
                            "score": post.get("score", 0),
                            "num_comments": post.get("num_comments", 0),
                        })
            except Exception as e:
                logger.debug(f"[sentiment] Keyword search error: {e}")

        if not posts:
            msg = f"'{keyword}'에 대한 소셜 데이터를 찾을 수 없습니다."
            if thread_ts:
                await self.slack.send_thread_reply(channel, thread_ts, msg)
            else:
                await self.say(msg, channel)
            return

        social_text = f"=== '{keyword}' 관련 Reddit 게시물 ===\n"
        for p in posts:
            social_text += f"[{p['source']}] {p['title']} (↑{p['score']}, 댓글{p['num_comments']})\n"

        analysis = await self._analyze_sentiment(social_text)
        if not analysis:
            msg = "분석에 실패했습니다."
            if thread_ts:
                await self.slack.send_thread_reply(channel, thread_ts, msg)
            else:
                await self.say(msg, channel)
            return

        overall = analysis.get("overall_score", 50)
        label = analysis.get("overall_label", "중립")
        summary = analysis.get("summary", "")
        bar = self._score_bar(overall)
        emoji = self._score_emoji(overall)

        msg = (
            f"{emoji} *'{keyword}' 소셜 센티멘트 분석*\n\n"
            f"감성 점수: *{overall}/100* ({label})\n"
            f"{bar}\n\n"
            f"분석 대상: Reddit {len(posts)}개 게시물\n\n"
            f"💡 {summary}\n\n"
            f"_투자 결정은 본인의 판단으로._"
        )
        if thread_ts:
            await self.slack.send_thread_reply(channel, thread_ts, msg)
        else:
            await self.say(msg, channel)

    # ── 유틸리티 ───────────────────────────────────────

    def _score_bar(self, score: int) -> str:
        """점수를 시각적 바로 표현"""
        filled = score // 5  # 0-20칸
        empty = 20 - filled
        if score <= 25:
            color = "🔴"
        elif score <= 45:
            color = "🟠"
        elif score <= 55:
            color = "🟡"
        elif score <= 75:
            color = "🟢"
        else:
            color = "🟢"
        return f"{color} {'█' * filled}{'░' * empty} {score}/100"

    def _mini_bar(self, score: int) -> str:
        """미니 바"""
        filled = score // 10
        empty = 10 - filled
        return f"{'▓' * filled}{'░' * empty}"

    def _score_emoji(self, score: int) -> str:
        if score <= 20:
            return "😱"
        elif score <= 35:
            return "😰"
        elif score <= 45:
            return "😟"
        elif score <= 55:
            return "😐"
        elif score <= 65:
            return "😊"
        elif score <= 80:
            return "😄"
        else:
            return "🤑"

    # ── 외부 작업 처리 ────────────────────────────────

    async def handle_external_task(self, task: TaskMessage):
        if task.task_type == "sentiment_check":
            context = await self.observe()
            if context:
                decision = await self.think(context)
                if decision:
                    return decision.get("analysis", {})
            return {"error": "No data available"}
        elif task.task_type == "keyword_sentiment":
            keyword = task.payload.get("keyword", "")
            if keyword:
                await self._analyze_keyword(keyword, self._target_channel)
                return {"status": "sent"}
            return {"error": "No keyword provided"}
        return await super().handle_external_task(task)
