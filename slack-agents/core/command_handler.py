"""
명령어 핸들러 (Command Handler)

모든 슬랙 !명령어 핸들러를 모아둔 모듈.
CommandHandler 클래스가 에이전트/서비스 참조를 갖고, 명령어를 디스패치.
기존 CommandRegistry 기능도 포함.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Any

logger = logging.getLogger("command_handler")

KST = timezone(timedelta(hours=9))


@dataclass
class CommandInfo:
    """명령어 메타데이터"""
    name: str
    handler: Callable[..., Awaitable[Any]]
    description: str = ""
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    category: str = "일반"


class CommandRegistry:
    """명령어 등록소 - 모든 슬랙 명령어를 한 곳에서 관리"""

    def __init__(self):
        self._commands: dict[str, CommandInfo] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
        description: str = "",
        usage: str = "",
        aliases: list[str] = None,
        category: str = "일반",
    ):
        """명령어 등록"""
        info = CommandInfo(
            name=name,
            handler=handler,
            description=description,
            usage=usage or f"!{name}",
            aliases=aliases or [],
            category=category,
        )
        self._commands[name] = info
        for alias in info.aliases:
            self._aliases[alias] = name
        logger.debug(f"명령어 등록: !{name} ({category})")

    def get(self, name: str) -> Callable[..., Awaitable[Any]] | None:
        """이름 또는 별칭으로 핸들러 조회"""
        if name in self._commands:
            return self._commands[name].handler
        if name in self._aliases:
            original = self._aliases[name]
            return self._commands[original].handler
        return None

    def get_info(self, name: str) -> CommandInfo | None:
        """명령어 메타데이터 조회"""
        if name in self._commands:
            return self._commands[name]
        if name in self._aliases:
            return self._commands[self._aliases[name]]
        return None

    def list_commands(self, category: str = None) -> list[CommandInfo]:
        """등록된 명령어 목록"""
        commands = list(self._commands.values())
        if category:
            commands = [c for c in commands if c.category == category]
        return sorted(commands, key=lambda c: c.name)

    def get_help(self) -> str:
        """전체 도움말 텍스트 생성"""
        lines = ["*📋 사용 가능한 명령어*\n"]
        categories = {}
        for cmd in self._commands.values():
            categories.setdefault(cmd.category, []).append(cmd)
        for cat, cmds in sorted(categories.items()):
            lines.append(f"*[{cat}]*")
            for cmd in sorted(cmds, key=lambda c: c.name):
                alias_str = f" (별칭: {', '.join('!' + a for a in cmd.aliases)})" if cmd.aliases else ""
                lines.append(f"  `{cmd.usage}` — {cmd.description}{alias_str}")
            lines.append("")
        return "\n".join(lines)

    @property
    def count(self) -> int:
        return len(self._commands)


class CommandHandler:
    """슬랙 명령어(!명령어) 핸들러 모음 - 모든 cmd_* 함수를 포함"""

    def __init__(
        self,
        slack,
        supabase,
        notion,
        ls_client,
        collector,
        curator,
        quote,
        diary_quote,
        diary_daily_alert,
        fortune,
        sentiment,
        bulletin,
        qa,
        proactive,
        auto_trader,
        market_info,
        swing_trader,
        invest_research,
        task_board,
        agent_hr,
        invest_monitor,
    ):
        self.slack = slack
        self.supabase = supabase
        self.notion = notion
        self.ls_client = ls_client
        self.collector = collector
        self.curator = curator
        self.quote = quote
        self.diary_quote = diary_quote
        self.diary_daily_alert = diary_daily_alert
        self.fortune = fortune
        self.sentiment = sentiment
        self.bulletin = bulletin
        self.qa = qa
        self.proactive = proactive
        self.auto_trader = auto_trader
        self.market_info = market_info
        self.swing_trader = swing_trader
        self.invest_research = invest_research
        self.task_board = task_board
        self.agent_hr = agent_hr
        self.invest_monitor = invest_monitor

        # 에이전트 결과물 노션 DB ID
        self.NOTION_AGENT_RESULTS_DB_ID = os.environ.get(
            "NOTION_AGENT_RESULTS_DB_ID",
            "1e21114e-6491-8101-8b67-ca52d78a8fb0",
        )

    async def _reply(self, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
        """스레드가 있으면 스레드로, 없으면 채널에 직접 전송"""
        if thread_ts:
            await self.slack.send_thread_reply(channel, thread_ts, text, also_send_to_channel=broadcast)
        else:
            await self.slack.send_message(channel, text)

    def register_all(self):
        """모든 명령어를 슬랙 클라이언트에 등록"""
        s = self.slack

        s.on_command("수집", self.cmd_collect)
        s.on_command("브리핑", self.cmd_briefing)
        s.on_command("상태", self.cmd_status)
        s.on_command("명언", self.cmd_quote)
        s.on_command("생각일기", self.cmd_diary_quote)
        s.on_command("일기분석", self.cmd_diary_daily_alert)
        s.on_command("로그", self.cmd_log)
        s.on_command("현황", self.cmd_dashboard)
        s.on_command("시세", self.cmd_market)
        s.on_command("인사평가", self.cmd_hr_eval)
        s.on_command("인사현황", self.cmd_hr_status)
        s.on_command("연봉", self.cmd_salary)
        s.on_command("투자현황", self.cmd_invest_status)
        s.on_command("qa", self.cmd_qa)
        s.on_command("QA", self.cmd_qa)
        s.on_command("큐에이", self.cmd_qa)
        s.on_command("테스트", self.cmd_qa)
        s.on_command("게시판", self.cmd_bulletin)
        s.on_command("블로그", self.cmd_blog)
        s.on_command("매수", self.cmd_buy)
        s.on_command("매도", self.cmd_sell)
        s.on_command("잔고", self.cmd_balance)
        s.on_command("시세조회", self.cmd_price)
        s.on_command("진단", self.cmd_diagnose)
        s.on_command("운세", self.cmd_fortune)
        s.on_command("센티멘트", self.cmd_sentiment)

    # ── 기본 명령어 ───────────────────────────────────────

    async def cmd_collect(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!수집 키워드 - 수집 에이전트에 키워드 수집 즉시 실행"""
        if args.strip():
            query = args.strip()
            self.curator.set_query_context(query, thread_ts=thread_ts, channel=channel)
            await self.collector._collect_by_keyword(query, user, thread_ts=thread_ts)
        else:
            await self._reply(channel, "사용법: `!수집 키워드`", thread_ts)

    async def cmd_briefing(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!브리핑 - 선별 에이전트에 즉시 브리핑 요청"""
        self.curator.set_query_context("브리핑", thread_ts=thread_ts, channel=channel)
        context = await self.curator.observe()
        if context:
            decision = await self.curator.think(context)
            if decision:
                await self.curator.act(decision)
        else:
            await self._reply(channel, "새로운 정보가 없습니다.", thread_ts)

    async def cmd_status(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!상태 - 전체 시스템 상태 확인"""
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        status_msg = f"*시스템 상태* ({now})\n"
        status_msg += f"- Collector: 실행 중 (간격: {self.collector.loop_interval}초)\n"
        status_msg += f"- Curator: 실행 중 (간격: {self.curator.loop_interval}초)\n"
        status_msg += f"- Curator 대기 버퍼: {len(self.curator._new_articles_buffer)}건\n"
        await self._reply(channel, status_msg, thread_ts)

    async def cmd_quote(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!명언 - 명언 에이전트 즉시 실행"""
        context = {
            "current_time": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "current_hour": datetime.now(KST).hour,
            "recent_conversations": [],
            "sent_history": self.quote._quote_history[-30:],
        }
        try:
            recent = await self.quote._fetch_recent_messages()
            context["recent_conversations"] = recent[:20]
        except Exception as e:
            logger.debug(f"[quote] Recent messages fetch failed: {e}")
        decision = await self.quote.think(context)
        if decision:
            decision["action"] = "send_quote"
            msg = self.quote._format_message(decision)
            await self._reply(channel, msg, thread_ts)
            self.quote._quote_history.append(f"{decision['quote_ko']} — {decision['author']}")
            self.quote._save_history()
        else:
            await self._reply(channel, "명언 생성에 실패했어요.", thread_ts)

    async def cmd_diary_quote(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!생각일기 - 생각일기 한 마디 즉시 실행"""
        err = await self.diary_quote.run_once(channel=channel, thread_ts=thread_ts)
        if err:
            await self._reply(channel, err, thread_ts)

    async def cmd_diary_daily_alert(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!일기분석 - 생각일기 분석알림 즉시 실행"""
        err = await self.diary_daily_alert.run_once(channel=channel, thread_ts=thread_ts)
        if err:
            await self._reply(channel, err, thread_ts)

    async def cmd_log(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!로그 - 요청사항 이력 보기"""
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "request_log.json")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.loads(f.read())
            if not logs:
                await self._reply(channel, "요청 이력이 없습니다.", thread_ts)
                return
            latest = logs[-1]
            lines = [f"📋 *요청사항 로그* ({latest['date']})\n"]
            for r in latest.get("requests", []):
                status = "✅" if r["status"] == "done" else "🔄"
                lines.append(f"{status} {r['request']}")
                lines.append(f"   _{r.get('changes', '')[:80]}_")
            await self._reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await self._reply(channel, f"로그 로드 실패: {e}", thread_ts)

    async def cmd_dashboard(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!현황 - 에이전트 가동 현황 보기"""
        from core import agent_tracker
        report = agent_tracker.get_status_report()
        await self._reply(channel, report, thread_ts)

    async def cmd_market(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!시세 - 투자 에이전트 즉시 브리핑 (현재 비활성화)"""
        try:
            await self._reply(channel, "시세 조회 기능은 현재 비활성화되어 있습니다.", thread_ts)
        except Exception as e:
            await self._reply(channel, f"시세 조회 실패: {e}", thread_ts)

    # ── HR 명령어 ──────────────────────────────────────────

    async def cmd_hr_eval(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!인사평가 - 전체 에이전트 일일 인사평가 실행"""
        await self._reply(channel, "📋 인사평가를 시작합니다...", thread_ts)
        try:
            result = await self.agent_hr.run_daily_evaluation()
            report = self.agent_hr.format_evaluation_result(result)
            await self._reply(channel, report, thread_ts)
        except Exception as e:
            await self._reply(channel, f"인사평가 실패: {e}", thread_ts)

    async def cmd_hr_status(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!인사현황 - 전체 에이전트 HR 현황"""
        if args.strip():
            report = self.agent_hr.get_agent_card(args.strip())
        else:
            report = self.agent_hr.get_hr_report()
        await self._reply(channel, report, thread_ts)

    async def cmd_salary(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!연봉 - 연봉 랭킹 또는 연봉 조정"""
        parts = args.strip().split()
        if len(parts) >= 2:
            agent_name = parts[0]
            try:
                amount = int(parts[1].replace("+", "").replace(",", ""))
                reason = " ".join(parts[2:]) if len(parts) > 2 else "수동 조정"
                result = self.agent_hr.adjust_salary(agent_name, amount, reason)
                profile = self.agent_hr.get_profile(agent_name) or {}
                display = profile.get("display_name", agent_name)
                await self._reply(channel,
                    f"💰 {display} 연봉 조정: {result['old_salary']:,}만원 → {result['new_salary']:,}만원",
                    thread_ts)
            except ValueError:
                await self._reply(channel, "사용법: `!연봉 에이전트명 +200 [사유]`", thread_ts)
        else:
            report = self.agent_hr.get_salary_ranking()
            await self._reply(channel, report, thread_ts)

    async def cmd_invest_status(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!투자현황 - 투자 에이전트 종합 모니터링 보고서"""
        await self._reply(channel, "📊 투자 에이전트 현황 분석 중...", thread_ts)
        try:
            days = 7
            if args.strip().isdigit():
                days = min(int(args.strip()), 30)
            evaluation = await self.invest_monitor.evaluate_invest_agents(days=days)
            report = self.invest_monitor.format_report(evaluation)
            await self._reply(channel, report, thread_ts)
        except Exception as e:
            logger.error(f"[invest_monitor] 투자현황 보고 실패: {e}")
            await self._reply(channel, f"투자현황 조회 실패: {e}", thread_ts)

    # ── QA / 게시판 / 블로그 ─────────────────────────────────

    async def cmd_qa(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!qa - QA 에이전트 즉시 테스트 실행"""
        await self._reply(channel, "QA 테스트 실행 중...", thread_ts)
        err = await self.qa.run_once(channel=channel, thread_ts=thread_ts)
        if err:
            await self._reply(channel, f"QA 실패: {err}", thread_ts)

    async def cmd_bulletin(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!게시판 - 게시판 스크래핑 즉시 실행 / 새 게시판 등록"""
        parts = args.strip().split(maxsplit=1)
        if not parts:
            await self._reply(channel, ":mag: 게시판 스크래핑 중...", thread_ts)
            await self.bulletin.scrape_and_show(channel, thread_ts, max_posts=5)
        elif parts[0] == "등록" and len(parts) > 1:
            reg_parts = parts[1].split()
            if len(reg_parts) < 2:
                await self._reply(channel, (
                    "사용법: `!게시판 등록 사이트이름 URL [auto|table|list] [playwright]`\n"
                    "• `playwright` 옵션: 해외IP 차단/JS 렌더링 사이트용 (Playwright 브라우저 사용)"
                ), thread_ts)
                return
            name = reg_parts[0]
            url = reg_parts[1]
            parser_type = "auto"
            use_playwright = False
            for opt in reg_parts[2:]:
                if opt.lower() in ("playwright", "pw", "브라우저"):
                    use_playwright = True
                elif opt in ("auto", "table", "list"):
                    parser_type = opt
            result = await self.bulletin._add_board(
                name=name, url=url, parser_type=parser_type,
                use_playwright=use_playwright,
            )
            if result.get("status") == "added":
                pw_label = " (Playwright 사용)" if use_playwright else ""
                await self._reply(channel, f":white_check_mark: *{name}* 게시판이 등록되었습니다.{pw_label}\nURL: {url}\n파서: {parser_type}", thread_ts)
            else:
                await self._reply(channel, f":x: 등록 실패: {result.get('message', '알 수 없는 오류')}", thread_ts)
        else:
            await self._reply(channel, (
                "사용법:\n"
                "• `!게시판` — 지금 스크래핑 실행\n"
                "• `!게시판 등록 이름 URL [auto|table|list] [playwright]` — 새 게시판 등록\n"
                "  - `playwright`: 해외IP 차단/JS 렌더링 사이트에 사용"
            ), thread_ts)

    async def _save_blog_to_notion(self, result: dict):
        """블로그 크롤링 결과를 노션 '에이전트 결과물' DB에 저장. (page_url, error) 튜플 반환."""
        from integrations.notion_client import NotionClient
        from agents.naver_blog_scraper import NaverBlogScraper as scraper_mod

        if not self.notion:
            return None, "notion 클라이언트 미초기화"
        if not result.get("success") or result.get("is_home"):
            return None, "저장 대상 아님"
        try:
            title = result.get("title", "(제목 없음)")
            properties = {
                "이름": NotionClient.prop_title(title),
            }
            content_blocks = scraper_mod.to_notion_blocks(result)
            logger.info(f"[Blog→Notion] 노션 저장 시도: {title}, 블록 {len(content_blocks)}개")
            first_batch = content_blocks[:100]
            page = await self.notion.create_page(
                database_id=self.NOTION_AGENT_RESULTS_DB_ID,
                properties=properties,
                content_blocks=first_batch,
            )
            if not page:
                return None, "create_page None 반환 (API 에러)"
            page_url = page.get("url", "")
            page_id = page.get("id", "")
            if len(content_blocks) > 100 and page_id:
                remaining = content_blocks[100:]
                for i in range(0, len(remaining), 100):
                    batch = remaining[i:i+100]
                    await self.notion.append_blocks(page_id, batch)
            logger.info(f"[Blog→Notion] 저장 완료: {title} → {page_url}")
            return page_url, None
        except Exception as e:
            logger.error(f"[Blog→Notion] 노션 저장 실패: {e}", exc_info=True)
            return None, str(e)

    async def cmd_blog(self, args: str, user: str, channel: str, thread_ts: str = None, fetch_posts: bool = False):
        """!블로그 URL [N] - 네이버 블로그 글 크롤링"""
        from agents.naver_blog_scraper import get_scraper as get_blog_scraper

        parts = args.strip().split()
        if not parts:
            await self._reply(channel, "사용법:\n• `!블로그 https://blog.naver.com/블로그ID/글번호` — 글 크롤링\n• `!블로그 https://blog.naver.com/블로그ID` — 최신 글 목록\n• `!블로그 https://blog.naver.com/블로그ID 5` — 최신 5개 글 본문까지 크롤링", thread_ts)
            return
        url = parts[0]
        max_posts = 5
        if len(parts) > 1 and parts[1].isdigit():
            max_posts = min(int(parts[1]), 10)
            fetch_posts = True
        await self._reply(channel, f":mag: 네이버 블로그 크롤링 중...", thread_ts)
        try:
            scraper = await get_blog_scraper()
            result = await asyncio.wait_for(
                scraper.scrape(url, max_posts=max_posts),
                timeout=120,
            )
            if result.get("is_home") and (fetch_posts or max_posts > 0) and result.get("posts"):
                post_urls = [p["url"] for p in result["posts"][:max_posts]]
                if fetch_posts and post_urls:
                    await self._reply(channel, f":house: *{result.get('blog_id', '')}* 블로그에서 최신 글 {len(post_urls)}개 크롤링 → 노션 저장합니다...", thread_ts)
                    for pu in post_urls:
                        post_result = await asyncio.wait_for(scraper.scrape(pu), timeout=120)
                        notion_url, err = await self._save_blog_to_notion(post_result)
                        post_title = post_result.get("title", "(제목 없음)")
                        if notion_url:
                            await self._reply(channel, f":white_check_mark: *{post_title}* → <{notion_url}|노션에서 보기>", thread_ts)
                        else:
                            msg = scraper.format_for_slack(post_result)
                            await self._reply(channel, msg, thread_ts)
                    return
            if result.get("success") and not result.get("is_home"):
                notion_url, err = await self._save_blog_to_notion(result)
                if notion_url:
                    post_title = result.get("title", "(제목 없음)")
                    await self._reply(channel, f":white_check_mark: *{post_title}* 크롤링 완료 → <{notion_url}|노션에서 보기>", thread_ts)
                    return
                else:
                    await self._reply(channel, f":warning: 노션 저장 실패 ({err}), 슬랙에 본문을 표시합니다.", thread_ts)
            msg = scraper.format_for_slack(result)
            await self._reply(channel, msg, thread_ts)
        except asyncio.TimeoutError:
            await self._reply(channel, ":x: 크롤링 타임아웃 (120초 초과). 잠시 후 다시 시도해주세요.", thread_ts)
        except Exception as e:
            logger.error(f"[Blog] 스크래핑 오류: {e}", exc_info=True)
            await self._reply(channel, f":x: 블로그 스크래핑 중 오류 발생: {e}", thread_ts)

    # ── 주식 매매 명령어 ──────────────────────────────────────

    async def cmd_buy(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!매수 종목코드 수량 [가격] - LS증권 매수 주문"""
        from integrations.ls_securities import friendly_error_message

        if not self.ls_client:
            await self._reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다. (LS_APP_KEY 환경변수 필요)", thread_ts)
            return
        parts = args.strip().split()
        if len(parts) < 2:
            await self._reply(channel, "사용법: `!매수 005930 1` (종목코드 수량) 또는 `!매수 005930 1 55000` (지정가)", thread_ts)
            return
        stock_code = parts[0]
        try:
            qty = int(parts[1])
        except ValueError:
            await self._reply(channel, "수량은 숫자여야 합니다.", thread_ts)
            return
        price = 0
        order_type = "03"
        if len(parts) >= 3:
            try:
                price = int(parts[2])
                order_type = "00"
            except ValueError:
                pass
        mode = "모의투자" if self.ls_client.paper_trading else "실전투자"
        price_str = f"{price:,}원" if price else "시장가"
        await self._reply(channel, f"📈 *[{mode}] 매수 주문 접수*\n종목: {stock_code} | 수량: {qty}주 | 가격: {price_str}", thread_ts)
        try:
            result = await self.ls_client.buy(stock_code=stock_code, qty=qty, price=price, order_type=order_type)
            if result.get("결과") == "성공":
                await self._reply(channel, f"✅ *매수 주문 성공!*\n주문번호: {result.get('주문번호')}\n종목: {result.get('종목코드', stock_code)} | {qty}주 | {price_str}", thread_ts)
            else:
                err_msg = result.get("에러", "")
                if not err_msg:
                    raw = result.get("raw", {})
                    err_msg = raw.get("rsp_msg", "") or raw.get("msg1", "") or str(raw)[:300]
                await self._reply(channel, f"❌ *매수 주문 실패*\n{err_msg}", thread_ts)
        except Exception as e:
            await self._reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_sell(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!매도 종목코드 수량 [가격] - LS증권 매도 주문"""
        from integrations.ls_securities import friendly_error_message

        if not self.ls_client:
            await self._reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        parts = args.strip().split()
        if len(parts) < 2:
            await self._reply(channel, "사용법: `!매도 005930 1` (종목코드 수량) 또는 `!매도 005930 1 55000` (지정가)", thread_ts)
            return
        stock_code = parts[0]
        try:
            qty = int(parts[1])
        except ValueError:
            await self._reply(channel, "수량은 숫자여야 합니다.", thread_ts)
            return
        price = 0
        order_type = "03"
        if len(parts) >= 3:
            try:
                price = int(parts[2])
                order_type = "00"
            except ValueError:
                pass
        mode = "모의투자" if self.ls_client.paper_trading else "실전투자"
        price_str = f"{price:,}원" if price else "시장가"
        await self._reply(channel, f"📉 *[{mode}] 매도 주문 접수*\n종목: {stock_code} | 수량: {qty}주 | 가격: {price_str}", thread_ts)
        try:
            result = await self.ls_client.sell(stock_code=stock_code, qty=qty, price=price, order_type=order_type)
            if result.get("결과") == "성공":
                await self._reply(channel, f"✅ *매도 주문 성공!*\n주문번호: {result.get('주문번호')}\n종목: {result.get('종목코드', stock_code)} | {qty}주 | {price_str}", thread_ts)
            else:
                err_msg = result.get("에러", "")
                if not err_msg:
                    raw = result.get("raw", {})
                    err_msg = raw.get("rsp_msg", "") or raw.get("msg1", "") or str(raw)[:300]
                await self._reply(channel, f"❌ *매도 주문 실패*\n{err_msg}", thread_ts)
        except Exception as e:
            await self._reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_balance(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!잔고 - LS증권 계좌 잔고 조회"""
        from integrations.ls_securities import friendly_error_message

        if not self.ls_client:
            await self._reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        try:
            result = await self.ls_client.get_balance()
            if result.get("unavailable"):
                from integrations.ls_securities import is_market_open, market_hours_message
                if not is_market_open():
                    await self._reply(channel, f"📋 표시할 잔고가 없습니다.\n{market_hours_message()}\n저장된 마지막 잔고가 없어서, 장중에 한 번 조회하면 이후 장외에서도 볼 수 있어요.", thread_ts)
                else:
                    err = result.get("error")
                    await self._reply(channel, f"❌ 잔고 조회에 실패했어요.\n{friendly_error_message(err) if err else '알 수 없는 오류'}", thread_ts)
                return
            summary = result.get("summary", {})
            holdings = result.get("holdings", [])
            is_cached = result.get("cached", False)
            mode = "모의투자" if self.ls_client.paper_trading else "실전투자"
            if is_cached:
                cached_time = result.get("cached_time")
                time_str = cached_time.strftime("%H:%M") if cached_time else "?"
                lines = [f"💰 *[{mode}] 계좌 잔고* (📋 {time_str} 기준 캐시)"]
            else:
                lines = [f"💰 *[{mode}] 계좌 잔고*"]
            lines.append(f"추정순자산: {summary.get('추정순자산', 0):,}원")
            lines.append(f"  예수금: {summary.get('예수금', 0):,}원 | 주문가능: {summary.get('주문가능금액', 0):,}원")
            lines.append(f"  보유주식평가: {summary.get('보유주식평가', 0):,}원")
            lines.append(f"총매입금액: {summary.get('총매입금액', 0):,}원")
            lines.append(f"추정손익: {summary.get('추정손익', 0):,}원")
            if holdings:
                lines.append("\n*보유 종목:*")
                for h in holdings:
                    pnl = h.get('평가손익', 0)
                    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                    eval_amt = h.get('평가금액', h.get('현재가', 0) * h.get('잔고수량', 0))
                    lines.append(f"{pnl_emoji} {h['종목명']} ({h['종목코드']}) | {h['잔고수량']}주 | {eval_amt:,}원 | 수익률: {h['수익률']:.1f}%")
            else:
                lines.append("\n보유 종목이 없습니다.")
            await self._reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await self._reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_price(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!시세조회 종목코드 - LS증권 현재가 조회"""
        from integrations.ls_securities import friendly_error_message

        if not self.ls_client:
            await self._reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        stock_code = args.strip()
        if not stock_code:
            await self._reply(channel, "사용법: `!시세조회 005930`", thread_ts)
            return
        try:
            from integrations.ls_securities import fetch_naver_volume
            result, naver_vol = await asyncio.gather(
                self.ls_client.get_price(stock_code),
                fetch_naver_volume(stock_code),
            )
            if result.get("unavailable"):
                from integrations.ls_securities import is_market_open, market_hours_message
                if not is_market_open():
                    await self._reply(channel, f"📋 {stock_code} 시세를 조회할 수 없습니다.\n{market_hours_message()}\n장중에 한 번 조회하면 이후 장외에서도 마지막 시세를 볼 수 있어요.", thread_ts)
                else:
                    err = result.get("error")
                    await self._reply(channel, f"❌ 시세 조회에 실패했어요.\n{friendly_error_message(err) if err else '알 수 없는 오류'}", thread_ts)
                return
            is_cached = result.get("cached", False)
            sign_map = {"1": "▲", "2": "▲", "3": "", "4": "▼", "5": "▼"}
            sign = sign_map.get(result.get("등락부호", ""), "")
            if is_cached:
                cached_time = result.get("cached_time")
                time_str = cached_time.strftime("%H:%M") if cached_time else "?"
                header = f"📊 *{result['종목명']}* ({stock_code}) _(📋 {time_str} 기준)_"
            else:
                header = f"📊 *{result['종목명']}* ({stock_code})"
            vol_line = f"거래량: {result['거래량']:,}"
            if naver_vol is not None:
                vol_line += f" (네이버: {naver_vol:,})"
            lines = [
                header,
                f"현재가: {result['현재가']:,}원 {sign}{abs(result['전일대비']):,}원 ({result['등락률']:+.2f}%)",
                vol_line,
                f"매수호가: {result['매수호가1']:,}원 | 매도호가: {result['매도호가1']:,}원",
                f"<https://finance.naver.com/item/main.naver?code={stock_code}|네이버 증권에서 확인>",
            ]
            await self._reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await self._reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_diagnose(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!진단 - LS증권 서버 연결 상태 진단"""
        import time as _time
        import httpx as _httpx

        lines = ["🔍 *LS증권 서버 연결 진단*\n"]
        app_key = self.ls_client.app_key
        app_secret = self.ls_client.app_secret
        for name, port in [("모의투자", 29080), ("실전", 8080)]:
            url = f"https://openapi.ls-sec.co.kr:{port}/oauth2/token"
            try:
                start = _time.time()
                test_http = _httpx.AsyncClient(timeout=10.0, verify=False)
                resp = await test_http.post(
                    url,
                    headers={"content-type": "application/x-www-form-urlencoded"},
                    data={"grant_type": "client_credentials", "appkey": app_key, "appsecretkey": app_secret, "scope": "oob"},
                )
                elapsed = _time.time() - start
                try:
                    body = resp.json()
                    token_ok = "access_token" in body
                    msg = body.get("rsp_msg", "") or body.get("error_description", "")
                except Exception:
                    token_ok = False
                    msg = resp.text[:100]
                if token_ok:
                    lines.append(f"✅ {name} ({port}): 토큰 발급 성공 ({elapsed:.1f}초)")
                else:
                    lines.append(f"⚠️ {name} ({port}): HTTP {resp.status_code} ({elapsed:.1f}초)\n   → {msg}")
                await test_http.aclose()
            except Exception as e:
                elapsed = _time.time() - start
                lines.append(f"❌ {name} ({port}): {type(e).__name__} ({elapsed:.1f}초)")
        lines.append(f"\n📋 *설정 정보*")
        lines.append(f"• 모드: {'모의투자' if self.ls_client.paper_trading else '실전투자'}")
        lines.append(f"• base_url: `{self.ls_client.base_url}`")
        lines.append(f"• app_key: `{app_key[:4]}...{app_key[-4:]}` ({len(app_key)}자)" if app_key else "• app_key: ❌ 미설정")
        lines.append(f"• app_secret: `{app_secret[:4]}...{app_secret[-4:]}` ({len(app_secret)}자)" if app_secret else "• app_secret: ❌ 미설정")
        lines.append(f"• account_no: `{self.ls_client.account_no}`" if self.ls_client.account_no else "• account_no: ❌ 미설정")
        from integrations.ls_securities import is_market_open as _is_mkt_open
        lines.append(f"• 장 운영시간: {'✅ 장중' if _is_mkt_open() else '❌ 장외'}")
        await self._reply(channel, "\n".join(lines), thread_ts)

    async def cmd_fortune(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!운세 - 운세 에이전트 즉시 실행"""
        now = datetime.now(KST)
        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "date_str": now.strftime("%Y년 %m월 %d일"),
            "weekday": ["월", "화", "수", "목", "금", "토", "일"][now.weekday()],
            "period": "아침" if now.hour < 11 else ("점심" if now.hour < 17 else "저녁"),
            "send_key": "manual",
            "recent_fortunes": [h.get("summary", "") for h in self.fortune._fortune_history[-10:]],
        }
        decision = await self.fortune.think(context)
        if decision:
            decision["action"] = "send_fortune"
            msg = self.fortune._format_message(decision)
            await self._reply(channel, msg, thread_ts)
            self.fortune._fortune_history.append({
                "date": context["date_str"],
                "period": context["period"],
                "summary": decision["data"].get("overall", "")[:100],
            })
            self.fortune._save_history()
        else:
            await self._reply(channel, "운세 생성에 실패했어요.", thread_ts)

    async def cmd_sentiment(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!센티멘트 - 소셜 센티멘트 분석 즉시 실행"""
        query = args.strip() if args.strip() else None
        if query:
            await self._reply(channel, f"🔍 *'{query}'* 소셜 센티멘트 분석 중...", thread_ts)
        else:
            await self._reply(channel, "🔍 소셜 센티멘트 종합 분석 중... (1-2분 소요)", thread_ts)
        await self.sentiment.run_manual(channel=channel, thread_ts=thread_ts, query=query)
