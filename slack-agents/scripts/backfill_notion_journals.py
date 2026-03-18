"""
과거 거래 내역(auto_trade_log)을 AI 분석하여 노션에 백필하는 일회성 스크립트.
trade_journal 테이블이 비어있으므로, 거래 로그에서 날짜별로 분석 생성 후 노션+Supabase에 저장.
Supabase SDK 대신 REST API 직접 호출.
"""

import asyncio
import json
import os
import sys

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
import httpx
from integrations.notion_client import NotionClient
from collections import defaultdict


SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://unuvbdqjgiypxfvlplpd.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_DB_ID = os.environ.get("NOTION_AGENT_RESULTS_DB_ID", "1e21114e-6491-8101-8b67-ca52d78a8fb0")


def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def main():
    if not all([SUPABASE_KEY, NOTION_API_KEY, ANTHROPIC_API_KEY]):
        print("필수 환경변수 누락: SUPABASE_SERVICE_ROLE_KEY, NOTION_API_KEY, ANTHROPIC_API_KEY")
        return

    http = httpx.AsyncClient(timeout=30.0)
    notion = NotionClient(NOTION_API_KEY)
    ai = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    # 전체 거래 로그 조회 (REST API)
    resp = await http.get(
        f"{SUPABASE_URL}/rest/v1/auto_trade_log",
        params={"select": "*", "order": "trade_time.asc"},
        headers=sb_headers(),
    )
    all_trades = resp.json()
    print(f"전체 거래: {len(all_trades)}건")

    # 날짜별 그룹
    by_date = defaultdict(list)
    for t in all_trades:
        date = t["trade_time"][:10]
        by_date[date].append(t)

    for date in sorted(by_date.keys()):
        trades = by_date[date]

        # 에이전트별 분리
        agent_trades = defaultdict(list)
        for t in trades:
            agent = t.get("agent_name", "auto_trader")
            agent_trades[agent].append(t)

        for agent_name, atrades in agent_trades.items():
            label = "자율거래" if agent_name == "auto_trader" else "스윙트레이딩"
            print(f"\n{'='*60}")
            print(f"{date} [{label}] {len(atrades)}건 분석 중...")

            buys = [t for t in atrades if t["action"] == "매수"]
            sells = [t for t in atrades if t["action"] == "매도"]
            total = len(atrades)
            win_count = sum(1 for t in sells if "익절" in (t.get("reason", "") or "").lower() and t["success"])
            loss_count = sum(1 for t in sells if "손절" in (t.get("reason", "") or "").lower() and t["success"])

            # 거래 내역 텍스트 (AI 프롬프트용은 최대 40건으로 제한)
            trade_lines = []
            for t in atrades:
                time_str = t["trade_time"][11:19] if len(t["trade_time"]) > 19 else t["trade_time"]
                status = "성공" if t["success"] else "실패"
                name = t.get("stock_name", t.get("stock_code", "?"))
                code = t.get("stock_code", "")
                qty = t.get("quantity", 0)
                reason = t.get("reason", "")
                price = t.get("price", 0)
                pnl_pct = t.get("pnl_pct")
                line = f"{time_str} {t['action']} {name}({code}) {qty}주 [{status}] {reason}"
                if price:
                    line += f" @{price:,}원"
                if pnl_pct is not None:
                    line += f" (수익률: {pnl_pct}%)"
                trade_lines.append(line)

            # 종목별 요약 추가 (AI 분석 정확도 향상)
            from collections import Counter
            stock_actions = defaultdict(lambda: {"매수": 0, "매도": 0, "익절": 0, "손절": 0})
            for t in atrades:
                name = t.get("stock_name", "?")
                stock_actions[name][t["action"]] += 1
                reason = (t.get("reason", "") or "").lower()
                if t["action"] == "매도" and t["success"]:
                    if "익절" in reason:
                        stock_actions[name]["익절"] += 1
                    elif "손절" in reason:
                        stock_actions[name]["손절"] += 1

            summary_lines = []
            for sname, acts in stock_actions.items():
                summary_lines.append(f"  {sname}: 매수 {acts['매수']}건, 매도 {acts['매도']}건 (익절 {acts['익절']}, 손절 {acts['손절']})")

            # AI 프롬프트용 거래 내역은 최대 40건
            prompt_trades = trade_lines[:40]
            if len(trade_lines) > 40:
                prompt_trades.append(f"... 외 {len(trade_lines) - 40}건 생략")
            trades_text = "\n".join(prompt_trades)
            summary_text = "\n".join(summary_lines)

            # AI 분석
            role = "데이트레이딩" if agent_name == "auto_trader" else "스윙 트레이딩"
            prompt = f"""당신은 {role} 코치입니다. 아래 매매 내역을 분석하고 교훈을 추출하세요.

## 매매 내역 ({date})
{trades_text}

## 종목별 요약
{summary_text}

## 통계
- 총 거래: {total}건 (매수 {len(buys)}, 매도 {len(sells)})
- 익절: {win_count}건, 손절: {loss_count}건

## 분석 요청
1. 잘한 점 정리 (구체적으로)
2. 못한 점 / 개선할 점 정리 (구체적으로)
3. 구체적 교훈 3~5개 추출 (다음 매매에 바로 적용할 수 있는 실전적 교훈)
4. 향후 전략 제안 (매수/매도/관망 방향, 주의해야 할 종목)

## 응답 규칙
- 반드시 순수 JSON만 출력 (```json 마크다운 금지)
- 각 항목은 1~2문장으로 간결하게
- lessons는 3~5개, good_points/bad_points는 각 2~3개

## 응답 형식
{{"lessons": ["교훈1", "교훈2"], "strategy_notes": "향후 전략 한 문단", "good_points": ["잘한점1"], "bad_points": ["개선점1"]}}"""

            try:
                resp = await ai.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.content[0].text.strip()
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                # 마지막 } 이후 잘라내기 (불완전 JSON 방지)
                last_brace = text.rfind("}")
                if last_brace > 0:
                    text = text[:last_brace + 1]

                analysis = json.loads(text)
                print(f"  분석 완료: {len(analysis.get('lessons', []))}개 교훈")

            except Exception as e:
                print(f"  AI 분석 실패: {e}")
                analysis = None

            # trade_journal에 저장
            if analysis:
                try:
                    journal_data = {
                        "journal_date": date,
                        "agent_name": agent_name,
                        "total_trades": total,
                        "win_count": win_count,
                        "loss_count": loss_count,
                        "total_pnl": 0,
                        "net_asset": 0,
                        "lessons": analysis.get("lessons", []),
                        "strategy_notes": analysis.get("strategy_notes", ""),
                        "raw_analysis": json.dumps(analysis, ensure_ascii=False),
                    }
                    headers = sb_headers()
                    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
                    jr = await http.post(
                        f"{SUPABASE_URL}/rest/v1/trade_journal",
                        json=journal_data,
                        headers=headers,
                    )
                    if jr.status_code < 300:
                        print(f"  trade_journal 저장 완료")
                    else:
                        print(f"  trade_journal 저장 실패: {jr.status_code} {jr.text}")
                except Exception as e:
                    print(f"  trade_journal 저장 실패: {e}")

            # 노션 저장
            try:
                # 기본 블록
                blocks = [
                    NotionClient.block_heading(f"{date} {label} 보고서"),
                    NotionClient.block_paragraph(
                        f"총 거래: {total}건 (매수 {len(buys)}, 매도 {len(sells)}) | 익절: {win_count}건 | 손절: {loss_count}건"
                    ),
                    NotionClient.block_divider(),
                    NotionClient.block_heading("거래 내역", level=3),
                ]

                for t in atrades:
                    time_str = t["trade_time"][11:19] if len(t["trade_time"]) > 19 else t["trade_time"]
                    s = "✅" if t["success"] else "❌"
                    name = t.get("stock_name", "?")
                    qty = t.get("quantity", 0)
                    reason = t.get("reason", "")
                    blocks.append(NotionClient.block_paragraph(
                        f"{s} {time_str} {t['action']} {name} {qty}주 - {reason}"
                    ))

                # AI 분석 블록
                if analysis:
                    blocks.append(NotionClient.block_divider())
                    blocks.append(NotionClient.block_heading("AI 매매 분석", level=2))

                    good_points = analysis.get("good_points", [])
                    if good_points:
                        blocks.append(NotionClient.block_heading("잘한 점", level=3))
                        for pt in good_points:
                            blocks.append(NotionClient.block_paragraph(f"✅ {pt}"))

                    bad_points = analysis.get("bad_points", [])
                    if bad_points:
                        blocks.append(NotionClient.block_heading("개선할 점", level=3))
                        for pt in bad_points:
                            blocks.append(NotionClient.block_paragraph(f"⚠️ {pt}"))

                    lessons = analysis.get("lessons", [])
                    if lessons:
                        blocks.append(NotionClient.block_heading("매매 교훈", level=3))
                        for lesson in lessons:
                            blocks.append(NotionClient.block_paragraph(f"💡 {lesson}"))

                    strategy = analysis.get("strategy_notes", "")
                    if strategy:
                        blocks.append(NotionClient.block_heading("향후 투자 전략", level=3))
                        blocks.append(NotionClient.block_paragraph(strategy))

                # 노션 블록 수 제한 (100개)
                if len(blocks) > 100:
                    blocks = blocks[:99]
                    blocks.append(NotionClient.block_paragraph("... (이하 생략)"))

                result = await notion.create_page(
                    database_id=NOTION_DB_ID,
                    properties={
                        "이름": NotionClient.prop_title(f"[{label}] {date} 일일 보고서 (백필)"),
                    },
                    content_blocks=blocks,
                )
                if result:
                    print(f"  노션 저장 완료: {result.get('id', '')[:8]}...")
                else:
                    print(f"  노션 저장 실패")

            except Exception as e:
                print(f"  노션 저장 실패: {e}")

    await http.aclose()
    await notion.close()
    print(f"\n{'='*60}")
    print("백필 완료!")


if __name__ == "__main__":
    asyncio.run(main())
