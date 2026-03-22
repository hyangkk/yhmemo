"""
디지털 상품 판매 에이전트

AI가 자동으로 디지털 상품을 생성하고, Gumroad에 등록하여 판매한다.
상품 종류: AI 프롬프트 팩, Notion 템플릿, 자동화 스크립트, 가이드 PDF 등

수익 흐름: 상품 생성 → Gumroad 등록 → 판매 → PayPal/은행 입금
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent
from core.browser_automation import get_browser

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# Gumroad API (가입 후 설정)
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN", "")

# 상품 카테고리별 템플릿
PRODUCT_TEMPLATES = {
    "prompt_pack": {
        "category": "AI 프롬프트",
        "price_usd": 5,
        "description_template": "전문가가 설계한 {topic} AI 프롬프트 {count}개 팩. Claude/GPT에서 즉시 사용 가능.",
        "file_format": "md",
    },
    "notion_template": {
        "category": "Notion 템플릿",
        "price_usd": 9,
        "description_template": "{topic} Notion 템플릿 - 바로 복제해서 사용 가능한 올인원 워크스페이스.",
        "file_format": "json",
    },
    "automation_script": {
        "category": "자동화 스크립트",
        "price_usd": 15,
        "description_template": "{topic} 자동화 Python 스크립트 - 설치 가이드 포함.",
        "file_format": "zip",
    },
    "guide": {
        "category": "가이드",
        "price_usd": 7,
        "description_template": "{topic} 완전 가이드 - 실전 예제와 템플릿 포함.",
        "file_format": "pdf",
    },
}

# 빠르게 만들 수 있는 상품 아이디어 (AI가 내용 생성)
QUICK_PRODUCTS = [
    {
        "type": "prompt_pack",
        "topic": "비즈니스 이메일 작성",
        "name": "Business Email AI Prompts Pack (50+)",
        "count": 50,
        "tags": ["ai", "prompts", "business", "email", "productivity"],
    },
    {
        "type": "prompt_pack",
        "topic": "블로그 글 작성",
        "name": "Blog Writing AI Prompts Master Pack (100+)",
        "count": 100,
        "tags": ["ai", "prompts", "writing", "blog", "content"],
    },
    {
        "type": "prompt_pack",
        "topic": "코딩 & 개발",
        "name": "Developer AI Prompts Toolkit (80+)",
        "count": 80,
        "tags": ["ai", "prompts", "coding", "developer", "programming"],
    },
    {
        "type": "prompt_pack",
        "topic": "마케팅 & SNS",
        "name": "Marketing & Social Media AI Prompts (60+)",
        "count": 60,
        "tags": ["ai", "prompts", "marketing", "social-media"],
    },
    {
        "type": "guide",
        "topic": "AI 자동화로 부업 시작하기",
        "name": "Start Your AI Side Hustle - Complete Guide",
        "count": 1,
        "tags": ["ai", "side-hustle", "automation", "guide", "income"],
    },
]


class DigitalProductAgent(BaseAgent):
    """디지털 상품 자동 생성 & 판매 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="digital_product",
            description="디지털 상품 자동 생성 및 Gumroad 판매",
            loop_interval=7200,  # 2시간마다 체크
            slack_channel=os.environ.get("CEO_CHANNEL", "C0AJJ469SV8"),
            **kwargs,
        )
        self._products_created = 0

    async def observe(self) -> dict | None:
        """판매 현황 및 신규 상품 필요 여부 확인"""
        now = datetime.now(KST)

        # 등록된 상품 수 확인
        try:
            result = self.supabase.table("digital_products").select("id, status").execute()
            products = result.data or []
            active = [p for p in products if p.get("status") == "active"]
            pending = [p for p in products if p.get("status") == "pending"]
        except Exception:
            products = []
            active = []
            pending = []

        # 판매 현황
        try:
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            sales = self.supabase.table("digital_product_sales").select("*").gte(
                "created_at", month_start.isoformat()
            ).execute()
            monthly_sales = sales.data or []
            monthly_revenue_usd = sum(s.get("amount_usd", 0) for s in monthly_sales)
        except Exception:
            monthly_sales = []
            monthly_revenue_usd = 0

        context = {
            "timestamp": now.isoformat(),
            "hour": now.hour,
            "total_products": len(products),
            "active_products": len(active),
            "pending_products": len(pending),
            "monthly_sales_count": len(monthly_sales),
            "monthly_revenue_usd": monthly_revenue_usd,
            "has_gumroad_token": bool(GUMROAD_ACCESS_TOKEN),
        }

        # 상품이 부족하면 생성 트리거
        if len(active) < 5:
            context["trigger"] = "create_product"
            context["products_needed"] = 5 - len(active)
        elif now.hour == 10:
            context["trigger"] = "daily_sales_report"
        else:
            return None  # 상품 충분하고 보고 시간 아니면 스킵

        return context

    async def think(self, context: dict) -> dict | None:
        """상품 생성 또는 판매 전략 판단"""
        trigger = context.get("trigger", "")

        if trigger == "create_product":
            # 아직 만들지 않은 상품 선택
            try:
                existing = self.supabase.table("digital_products").select("name").execute()
                existing_names = {p["name"] for p in (existing.data or [])}
            except Exception:
                existing_names = set()

            for product in QUICK_PRODUCTS:
                if product["name"] not in existing_names:
                    return {
                        "action": "create_product",
                        "product": product,
                    }

            # 모든 기본 상품 소진 → AI에게 새 아이디어 요청
            return await self._generate_new_product_idea(context)

        elif trigger == "daily_sales_report":
            return {
                "action": "sales_report",
                "context": context,
            }

        return None

    async def _generate_new_product_idea(self, context: dict) -> dict | None:
        """AI가 새 상품 아이디어 생성"""
        system_prompt = """당신은 디지털 상품 기획자입니다.
Gumroad에서 잘 팔리는 디지털 상품 아이디어를 하나 제안하세요.

규칙:
- $5~$20 가격대
- AI/자동화/생산성 관련
- 영어로 제목과 설명 (글로벌 판매)
- AI가 내용을 바로 생성 가능한 것

JSON 형식:
{"type": "prompt_pack|guide|automation_script", "topic": "주제", "name": "영어 상품명", "count": 숫자, "tags": ["태그1", "태그2"]}"""

        try:
            resp = await self.ai_think(system_prompt, "새 상품 아이디어를 하나 제안해주세요.", model="claude-haiku-4-5-20251001")
            text = resp.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            product = json.loads(text)
            return {"action": "create_product", "product": product}
        except Exception as e:
            logger.error(f"[digital_product] 아이디어 생성 실패: {e}")
            return None

    async def act(self, decision: dict):
        """결정 실행"""
        action = decision.get("action", "")

        if action == "create_product":
            await self._create_and_register_product(decision["product"])
        elif action == "sales_report":
            await self._send_sales_report(decision["context"])

    async def _create_and_register_product(self, product: dict):
        """상품 콘텐츠 생성 → Gumroad 등록"""
        product_type = product.get("type", "prompt_pack")
        topic = product.get("topic", "")
        name = product.get("name", "")
        count = product.get("count", 50)
        tags = product.get("tags", [])

        template = PRODUCT_TEMPLATES.get(product_type, PRODUCT_TEMPLATES["prompt_pack"])
        price_usd = template["price_usd"]

        await self.log(f"🏭 *[상품 생성 시작]* {name}\n타입: {product_type} | 가격: ${price_usd}")

        # 1. AI로 상품 콘텐츠 생성
        content = await self._generate_product_content(product_type, topic, name, count)
        if not content:
            await self.log(f"❌ 상품 콘텐츠 생성 실패: {name}")
            return

        # 2. 파일 저장
        safe_name = name.replace(" ", "_").replace("/", "_")[:50]
        file_path = f"/tmp/products/{safe_name}.md"
        os.makedirs("/tmp/products", exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # 3. DB에 상품 등록 (pending)
        try:
            self.supabase.table("digital_products").insert({
                "name": name,
                "product_type": product_type,
                "topic": topic,
                "price_usd": price_usd,
                "price_cents": price_usd * 100,
                "tags": tags,
                "file_path": file_path,
                "status": "pending",
                "platform": "gumroad",
                "created_at": datetime.now(KST).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"[digital_product] DB 저장 실패: {e}")

        # 4. Gumroad API로 등록 (토큰이 있는 경우)
        if GUMROAD_ACCESS_TOKEN:
            gumroad_result = await self._register_on_gumroad(name, content, price_usd, tags)
            if gumroad_result.get("success"):
                await self.log(
                    f"✅ *[Gumroad 등록 완료]* {name}\n"
                    f"가격: ${price_usd} | URL: {gumroad_result.get('url', '?')}"
                )
                # DB 업데이트
                try:
                    self.supabase.table("digital_products").update({
                        "status": "active",
                        "gumroad_url": gumroad_result.get("url", ""),
                        "gumroad_id": gumroad_result.get("product_id", ""),
                    }).eq("name", name).execute()
                except Exception:
                    pass
            else:
                await self.log(f"⚠️ Gumroad 등록 실패: {gumroad_result.get('error', '?')}")
        else:
            # Gumroad 토큰 없으면 브라우저로 등록 시도
            await self.log(
                f"📝 *[상품 생성 완료 - Gumroad 미등록]*\n"
                f"이름: {name}\n가격: ${price_usd}\n"
                f"파일: {file_path}\n"
                f"_Gumroad 가입 후 등록 필요 (CEO에게 요청)_"
            )

            # CEO에게 등록 요청
            try:
                await self.ask_agent("ceo", "request_owner", {
                    "request": (
                        f"Gumroad 가입이 필요합니다.\n"
                        f"이메일: ai.agent.yh@gmail.com\n"
                        f"가입 URL: https://app.gumroad.com/signup\n"
                        f"가입 후 Access Token을 secrets_vault에 GUMROAD_ACCESS_TOKEN으로 저장해주세요.\n"
                        f"대기 중인 상품: {name} (${price_usd})"
                    ),
                })
            except Exception:
                pass

    async def _generate_product_content(self, product_type: str, topic: str, name: str, count: int) -> str | None:
        """AI로 상품 콘텐츠 생성"""
        if product_type == "prompt_pack":
            system_prompt = f"""Create a professional AI prompt pack about "{topic}".
Generate exactly {count} high-quality prompts.

Format each prompt as:
## Prompt [number]: [Title]
**Category:** [category]
**Best for:** [use case]

```
[The actual prompt text, ready to copy-paste into ChatGPT/Claude]
```

---

Make prompts specific, actionable, and immediately useful.
Include variables in [brackets] for customization.
Write everything in English."""

        elif product_type == "guide":
            system_prompt = f"""Write a comprehensive guide about "{topic}".

Structure:
# {name}

## Table of Contents
## Chapter 1: Introduction
## Chapter 2-8: Core content chapters
## Chapter 9: Templates & Checklists
## Chapter 10: Resources & Next Steps

Requirements:
- Practical, actionable advice
- Real examples and case studies
- Templates and checklists included
- 3000+ words
- Written in English
- Professional but approachable tone"""

        else:
            system_prompt = f"Create a digital product about '{topic}'. Name: {name}. Make it professional and valuable."

        try:
            response = await self.ai_think(
                system_prompt,
                f"Create the full content for: {name}",
                model="claude-haiku-4-5-20251001",
                max_tokens=8000,
            )
            return response
        except Exception as e:
            logger.error(f"[digital_product] 콘텐츠 생성 실패: {e}")
            return None

    async def _register_on_gumroad(self, name: str, content: str, price_usd: int, tags: list) -> dict:
        """Gumroad API로 상품 등록"""
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                # Gumroad API: 상품 생성
                resp = await client.post(
                    "https://api.gumroad.com/v2/products",
                    data={
                        "access_token": GUMROAD_ACCESS_TOKEN,
                        "name": name,
                        "price": price_usd * 100,  # cents
                        "description": content[:5000],  # Gumroad 제한
                        "tags": ",".join(tags[:5]),
                        "published": "true",
                    },
                    timeout=30,
                )
                result = resp.json()

                if result.get("success"):
                    product = result.get("product", {})
                    return {
                        "success": True,
                        "product_id": product.get("id", ""),
                        "url": product.get("short_url", ""),
                    }
                else:
                    return {"success": False, "error": result.get("message", "Unknown error")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _send_sales_report(self, context: dict):
        """판매 현황 보고"""
        report = (
            f"💰 *[디지털 상품 판매 보고]*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"등록 상품: {context.get('total_products', 0)}개\n"
            f"활성 상품: {context.get('active_products', 0)}개\n"
            f"이번 달 판매: {context.get('monthly_sales_count', 0)}건\n"
            f"이번 달 수익: ${context.get('monthly_revenue_usd', 0):.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        await self.log(report)

    async def handle_external_task(self, task):
        """외부 요청 처리"""
        if task.task_type == "create_product":
            await self._create_and_register_product(task.payload)
            return {"status": "created"}
        elif task.task_type == "sales_status":
            try:
                result = self.supabase.table("digital_products").select("*").execute()
                return {"products": result.data or []}
            except Exception:
                return {"products": []}
        return await super().handle_external_task(task)

    async def log(self, message: str):
        if self.slack and self.slack_channel:
            try:
                await self.slack.post_message(self.slack_channel, message)
            except Exception as e:
                logger.error(f"[digital_product] 슬랙 전송 실패: {e}")
