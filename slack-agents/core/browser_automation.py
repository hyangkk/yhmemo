"""
브라우저 자동화 모듈

Playwright 기반 헤드리스 Chromium으로 웹사이트 자동 조작.
가입, 로그인, 폼 입력, 스크린샷, 데이터 수집 등을 수행한다.

Fly.io 서버에서 24/7 가동 가능.
"""

import asyncio
import logging
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 비즈니스 이메일 (secrets_vault에서 로드)
BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "ai.agent.yh@gmail.com")
BUSINESS_PASSWORD = os.environ.get("BUSINESS_EMAIL_PASSWORD", "yhagentai")


class BrowserAutomation:
    """Playwright 기반 브라우저 자동화"""

    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        """브라우저 인스턴스 보장"""
        if self._browser and self._browser.is_connected():
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        logger.info("[browser] Chromium 브라우저 시작됨")

    async def close(self):
        """브라우저 종료"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def new_context(self, **kwargs):
        """새 브라우저 컨텍스트 (쿠키/세션 격리)"""
        await self._ensure_browser()
        return await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            **kwargs,
        )

    # ── 핵심 액션들 ──────────────────────────────────────

    async def screenshot(self, url: str, path: str = "/tmp/screenshot.png") -> str:
        """URL 스크린샷 캡처"""
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.screenshot(path=path, full_page=True)
            logger.info(f"[browser] 스크린샷 저장: {path}")
            return path
        finally:
            await ctx.close()

    async def get_page_text(self, url: str) -> str:
        """페이지 텍스트 추출"""
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            text = await page.inner_text("body")
            return text[:10000]  # 최대 10000자
        finally:
            await ctx.close()

    async def fill_form(self, url: str, fields: dict, submit_selector: str = None) -> dict:
        """폼 자동 입력 및 제출

        Args:
            url: 폼이 있는 URL
            fields: {selector: value} 딕셔너리
            submit_selector: 제출 버튼 선택자 (없으면 제출 안 함)

        Returns:
            {"success": bool, "final_url": str, "screenshot": str}
        """
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            for selector, value in fields.items():
                await page.fill(selector, value)
                await asyncio.sleep(0.3)

            screenshot_path = f"/tmp/form_{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}.png"

            if submit_selector:
                await page.click(submit_selector)
                await page.wait_for_load_state("networkidle", timeout=15000)

            await page.screenshot(path=screenshot_path)

            return {
                "success": True,
                "final_url": page.url,
                "screenshot": screenshot_path,
            }
        except Exception as e:
            logger.error(f"[browser] 폼 입력 실패: {e}")
            return {"success": False, "error": str(e)}
        finally:
            await ctx.close()

    # ── 가입 자동화 ──────────────────────────────────────

    async def signup_generic(
        self,
        url: str,
        email: str = None,
        password: str = None,
        extra_fields: dict = None,
    ) -> dict:
        """범용 가입 자동화 (AI 기반 폼 탐색)

        1. 가입 페이지 로드
        2. 이메일/비밀번호 필드 자동 탐지
        3. 입력 후 제출
        4. 결과 스크린샷 반환
        """
        email = email or BUSINESS_EMAIL
        password = password or BUSINESS_PASSWORD
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 이메일 필드 탐지 (우선순위대로 시도)
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="user[email]"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="이메일" i]',
                'input[id*="email" i]',
            ]
            email_filled = False
            for sel in email_selectors:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.fill(sel, email)
                        email_filled = True
                        break
                except Exception:
                    continue

            # 비밀번호 필드 탐지
            pw_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="user[password]"]',
                'input[id*="password" i]',
            ]
            pw_filled = False
            for sel in pw_selectors:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.fill(sel, password)
                        pw_filled = True
                        break
                except Exception:
                    continue

            # 추가 필드
            if extra_fields:
                for sel, val in extra_fields.items():
                    try:
                        await page.fill(sel, val)
                    except Exception:
                        pass

            # 제출 버튼 탐지
            submit_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Sign up")',
                'button:has-text("Register")',
                'button:has-text("Create account")',
                'button:has-text("가입")',
                'button:has-text("회원가입")',
            ]
            submitted = False
            for sel in submit_selectors:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.click(sel)
                        submitted = True
                        break
                except Exception:
                    continue

            if submitted:
                await page.wait_for_load_state("networkidle", timeout=15000)

            # 결과 스크린샷
            ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"/tmp/signup_{ts}.png"
            await page.screenshot(path=screenshot_path)

            return {
                "success": True,
                "email_filled": email_filled,
                "password_filled": pw_filled,
                "submitted": submitted,
                "final_url": page.url,
                "screenshot": screenshot_path,
            }
        except Exception as e:
            logger.error(f"[browser] 가입 실패: {e}")
            return {"success": False, "error": str(e)}
        finally:
            await ctx.close()

    # ── Google 로그인 (OAuth) ────────────────────────────

    async def google_login(self, url: str) -> dict:
        """Google OAuth 로그인 시도

        많은 서비스가 Google 로그인을 지원.
        headless에서는 reCAPTCHA 등으로 차단될 수 있음 → 결과 반환.
        """
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Google 로그인 버튼 찾기
            google_selectors = [
                'a:has-text("Google")',
                'button:has-text("Google")',
                '[data-provider="google"]',
                '.google-login',
                'a[href*="accounts.google.com"]',
            ]
            clicked = False
            for sel in google_selectors:
                try:
                    if await page.locator(sel).count() > 0:
                        await page.click(sel)
                        clicked = True
                        break
                except Exception:
                    continue

            if clicked:
                await page.wait_for_load_state("networkidle", timeout=15000)

                # Google 로그인 페이지에서 이메일 입력
                try:
                    await page.fill('input[type="email"]', BUSINESS_EMAIL)
                    await page.click("#identifierNext")
                    await page.wait_for_load_state("networkidle", timeout=10000)

                    # 비밀번호 입력
                    await asyncio.sleep(2)
                    await page.fill('input[type="password"]', BUSINESS_PASSWORD)
                    await page.click("#passwordNext")
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception as e:
                    logger.warning(f"[browser] Google 로그인 중 오류: {e}")

            ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"/tmp/google_login_{ts}.png"
            await page.screenshot(path=screenshot_path)

            return {
                "success": clicked,
                "final_url": page.url,
                "screenshot": screenshot_path,
            }
        except Exception as e:
            logger.error(f"[browser] Google 로그인 실패: {e}")
            return {"success": False, "error": str(e)}
        finally:
            await ctx.close()

    # ── AI 기반 자유 탐색 ────────────────────────────────

    async def ai_browse(self, url: str, instructions: str, ai_client=None) -> dict:
        """AI가 지시사항에 따라 웹페이지를 자유롭게 탐색

        Args:
            url: 시작 URL
            instructions: AI에게 줄 지시사항 (예: "가입 페이지를 찾아서 이메일로 가입해")
            ai_client: Anthropic AsyncAnthropic 클라이언트

        Returns:
            {"steps": [...], "final_url": str, "screenshot": str, "result": str}
        """
        ctx = await self.new_context()
        steps = []
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)

            for step_num in range(10):  # 최대 10단계
                # 현재 페이지 상태 수집
                page_info = {
                    "url": page.url,
                    "title": await page.title(),
                    "text_preview": (await page.inner_text("body"))[:3000],
                }

                # 클릭 가능한 요소 수집
                clickables = await page.evaluate("""() => {
                    const elements = [];
                    document.querySelectorAll('a, button, input[type="submit"]').forEach((el, i) => {
                        if (i < 30 && el.offsetParent !== null) {
                            elements.push({
                                tag: el.tagName,
                                text: el.innerText?.slice(0, 100) || '',
                                href: el.href || '',
                                type: el.type || '',
                                id: el.id || '',
                                name: el.name || '',
                            });
                        }
                    });
                    return elements;
                }""")

                # 입력 필드 수집
                inputs = await page.evaluate("""() => {
                    const fields = [];
                    document.querySelectorAll('input, textarea, select').forEach((el, i) => {
                        if (i < 20 && el.offsetParent !== null) {
                            fields.push({
                                tag: el.tagName,
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                placeholder: el.placeholder || '',
                                value: el.value || '',
                            });
                        }
                    });
                    return fields;
                }""")

                page_info["clickable_elements"] = clickables
                page_info["input_fields"] = inputs

                if not ai_client:
                    steps.append({"step": step_num, "page": page_info, "action": "no_ai_client"})
                    break

                # AI에게 다음 행동 결정 요청
                ai_prompt = f"""당신은 웹 브라우저를 조작하는 AI입니다.

지시사항: {instructions}
비즈니스 이메일: {BUSINESS_EMAIL}
비즈니스 비밀번호: {BUSINESS_PASSWORD}

현재 페이지:
URL: {page_info['url']}
제목: {page_info['title']}
텍스트 일부: {page_info['text_preview'][:1500]}

클릭 가능 요소: {json.dumps(clickables[:15], ensure_ascii=False)}
입력 필드: {json.dumps(inputs[:10], ensure_ascii=False)}

다음 행동을 JSON으로 답하세요:
{{"action": "click|fill|done|fail", "selector": "CSS선택자", "value": "입력값(fill일때)", "reason": "이유"}}
- click: 요소 클릭
- fill: 입력 필드 채우기
- done: 목표 달성 완료
- fail: 더 이상 진행 불가"""

                try:
                    resp = await ai_client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=500,
                        messages=[{"role": "user", "content": ai_prompt}],
                    )
                    ai_text = resp.content[0].text.strip()
                    if "```json" in ai_text:
                        ai_text = ai_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in ai_text:
                        ai_text = ai_text.split("```")[1].split("```")[0].strip()

                    action = json.loads(ai_text)
                except Exception as e:
                    logger.error(f"[browser] AI 판단 오류 (step {step_num}): {e}")
                    steps.append({"step": step_num, "error": str(e)})
                    break

                steps.append({"step": step_num, "url": page.url, "action": action})

                # 행동 실행
                if action["action"] == "done":
                    break
                elif action["action"] == "fail":
                    break
                elif action["action"] == "click":
                    try:
                        await page.click(action["selector"], timeout=5000)
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception as e:
                        steps.append({"step": step_num, "click_error": str(e)})
                elif action["action"] == "fill":
                    try:
                        await page.fill(action["selector"], action.get("value", ""))
                    except Exception as e:
                        steps.append({"step": step_num, "fill_error": str(e)})

                await asyncio.sleep(1)

            # 최종 스크린샷
            ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"/tmp/ai_browse_{ts}.png"
            await page.screenshot(path=screenshot_path)

            last_action = steps[-1].get("action", {}) if steps else {}
            return {
                "success": last_action.get("action") == "done" if isinstance(last_action, dict) else False,
                "steps": steps,
                "step_count": len(steps),
                "final_url": page.url,
                "screenshot": screenshot_path,
                "result": last_action.get("reason", "") if isinstance(last_action, dict) else "",
            }
        except Exception as e:
            logger.error(f"[browser] AI 탐색 실패: {e}")
            return {"success": False, "error": str(e), "steps": steps}
        finally:
            await ctx.close()

    # ── 플랫폼별 가입 헬퍼 ───────────────────────────────

    async def signup_gumroad(self) -> dict:
        """Gumroad 가입"""
        return await self.signup_generic(
            url="https://app.gumroad.com/signup",
            email=BUSINESS_EMAIL,
            password=BUSINESS_PASSWORD,
        )

    async def signup_producthunt(self) -> dict:
        """Product Hunt 가입"""
        return await self.signup_generic(
            url="https://www.producthunt.com/",
            email=BUSINESS_EMAIL,
            password=BUSINESS_PASSWORD,
        )

    async def signup_promptbase(self) -> dict:
        """PromptBase 가입"""
        return await self.signup_generic(
            url="https://promptbase.com/signup",
            email=BUSINESS_EMAIL,
            password=BUSINESS_PASSWORD,
        )

    async def signup_etsy(self) -> dict:
        """Etsy 가입 (디지털 상품 판매)"""
        return await self.signup_generic(
            url="https://www.etsy.com/join",
            email=BUSINESS_EMAIL,
            password=BUSINESS_PASSWORD,
        )


# 싱글톤
_instance: Optional[BrowserAutomation] = None


def get_browser() -> BrowserAutomation:
    """브라우저 자동화 싱글톤 반환"""
    global _instance
    if _instance is None:
        _instance = BrowserAutomation()
    return _instance
