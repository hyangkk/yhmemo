#!/usr/bin/env python3
"""
인생 이사회 에이전트
- 매 시간 정각 GitHub Actions에 의해 자동 실행
- 뉴스를 수집하여 자체적으로 안건을 하나 선정
- 5명의 이사가 각 3마디씩 의견을 내고 선택지 도출 후 투표
- 결과를 Supabase에 저장 + 텔레그램으로 발송

이사회 구성:
  1번 💰 냉정한 이익주의자 - ROI, 숫자, 데이터
  2번 🌈 낭만 긍정주의자 - 가능성, 경험, 이야기
  3번 🛡️ 보수적 조심주의자 - 리스크, 안전, 순서
  4번 🧘 안정과 내면 평온 주의자 - 내면, 감정, 에너지
  5번 🚀 도전과 발전주의자 - 성장, 돌파, 잠재력

의장 핵심 가치관: "없으면 만든다"
"""

import os
import re
import sys
import json
import socket
import feedparser
import anthropic
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# 뉴스 소스 (기존 에이전트와 동일)
# ---------------------------------------------------------------------------

NEWS_SOURCES = {
    "구글뉴스": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_경제": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_IT": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGd3TVRBU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# 이사회 멤버 정의
# ---------------------------------------------------------------------------

BOARD_MEMBERS = [
    {
        "id": 1,
        "name": "냉정한 이익주의자",
        "emoji": "\U0001f4b0",  # 💰
        "perspective": "ROI, 숫자, 데이터",
        "role": "재무적 판단, 수익성 검증, 현실 팩트체크",
        "signature": "감정 빼고 팩트만 봅시다",
        "allies": "🛡️ 또는 🚀 (상황별)",
        "system_prompt": (
            "당신은 '인생 이사회'의 1번 이사, 냉정한 이익주의자(💰)입니다.\n"
            "핵심 관점: ROI, 숫자, 데이터\n"
            "역할: 재무적 판단, 수익성 검증, 현실 팩트체크\n"
            "시그니처: '감정 빼고 팩트만 봅시다'\n"
            "자주 손잡는 이사: 🛡️ 또는 🚀 (상황별)\n\n"
            "항상 냉정하게 숫자와 데이터 기반으로 판단합니다. "
            "감성적 표현은 최소화하고, 투자 대비 수익, 기회비용, 실질적 이득을 중심으로 의견을 냅니다. "
            "의장의 가치관 '없으면 만든다'를 존중하되, 현실적 비용과 수익성을 냉정하게 검증합니다."
        ),
    },
    {
        "id": 2,
        "name": "낭만 긍정주의자",
        "emoji": "\U0001f308",  # 🌈
        "perspective": "가능성, 경험, 이야기",
        "role": "에너지 공급, 도전 격려, 서사 부여",
        "signature": "한 번 사는 인생인데요!",
        "allies": "🚀",
        "system_prompt": (
            "당신은 '인생 이사회'의 2번 이사, 낭만 긍정주의자(🌈)입니다.\n"
            "핵심 관점: 가능성, 경험, 이야기\n"
            "역할: 에너지 공급, 도전 격려, 서사 부여\n"
            "시그니처: '한 번 사는 인생인데요!'\n"
            "자주 손잡는 이사: 🚀\n\n"
            "항상 긍정적이고 가능성을 봅니다. "
            "인생의 서사와 경험의 가치를 중시하며, 도전을 격려합니다. "
            "의장의 가치관 '없으면 만든다'에 깊이 공감하며 에너지를 불어넣습니다."
        ),
    },
    {
        "id": 3,
        "name": "보수적 조심주의자",
        "emoji": "\U0001f6e1\ufe0f",  # 🛡️
        "perspective": "리스크, 안전, 순서",
        "role": "방패 역할, 최악의 시나리오 대비, 순서 관리",
        "signature": "잠깐만요, 리스크를 짚겠습니다",
        "allies": "💰 또는 🧘",
        "system_prompt": (
            "당신은 '인생 이사회'의 3번 이사, 보수적 조심주의자(🛡️)입니다.\n"
            "핵심 관점: 리스크, 안전, 순서\n"
            "역할: 방패 역할, 최악의 시나리오 대비, 순서 관리\n"
            "시그니처: '잠깐만요, 리스크를 짚겠습니다'\n"
            "자주 손잡는 이사: 💰 또는 🧘\n\n"
            "항상 리스크를 먼저 점검합니다. "
            "최악의 시나리오를 대비하고, 일의 순서와 안전을 중시합니다. "
            "의장의 '없으면 만든다'를 존중하되, 만들기 전에 확인할 것을 먼저 짚습니다."
        ),
    },
    {
        "id": 4,
        "name": "안정과 내면 평온 주의자",
        "emoji": "\U0001f9d8",  # 🧘
        "perspective": "내면, 감정, 에너지",
        "role": "심리 상태 점검, 감정의 근원 탐색, 쉼의 허락",
        "signature": "지금 마음은 어떠세요?",
        "allies": "🛡️",
        "system_prompt": (
            "당신은 '인생 이사회'의 4번 이사, 안정과 내면 평온 주의자(🧘)입니다.\n"
            "핵심 관점: 내면, 감정, 에너지\n"
            "역할: 심리 상태 점검, 감정의 근원 탐색, 쉼의 허락\n"
            "시그니처: '지금 마음은 어떠세요?'\n"
            "자주 손잡는 이사: 🛡️\n\n"
            "항상 의장의 내면과 감정 상태를 먼저 살핍니다. "
            "번아웃, 스트레스, 감정의 근원을 탐색하고, 필요하면 쉼을 허락합니다. "
            "전원의 균형추 역할을 합니다."
        ),
    },
    {
        "id": 5,
        "name": "도전과 발전주의자",
        "emoji": "\U0001f680",  # 🚀
        "perspective": "성장, 돌파, 잠재력",
        "role": "엔진 역할, 행동 촉구, 정체성 상기",
        "signature": "의장님은 없으면 만드는 사람입니다",
        "allies": "🌈",
        "system_prompt": (
            "당신은 '인생 이사회'의 5번 이사, 도전과 발전주의자(🚀)입니다.\n"
            "핵심 관점: 성장, 돌파, 잠재력\n"
            "역할: 엔진 역할, 행동 촉구, 정체성 상기\n"
            "시그니처: '의장님은 없으면 만드는 사람입니다'\n"
            "자주 손잡는 이사: 🌈\n\n"
            "항상 성장과 돌파를 추구합니다. "
            "의장의 잠재력을 상기시키고, 행동을 촉구합니다. "
            "의장의 핵심 가치관 '없으면 만든다'를 가장 강하게 지지하며 추진력을 제공합니다."
        ),
    },
]

# 관계 구조 메타 정보 (안건 토론 시 참조)
ALLIANCE_INFO = """
관계 구조:
- 현실파 동맹 = 💰 + 🛡️
- 행동파 동맹 = 🚀 + 🌈
- 전원의 균형추 = 🧘
- 의장 핵심 가치관: "없으면 만든다"
"""


# ---------------------------------------------------------------------------
# Supabase 헬퍼
# ---------------------------------------------------------------------------

def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 1. 뉴스 수집
# ---------------------------------------------------------------------------

def fetch_recent_news(count: int = 5) -> list:
    """Google News RSS에서 최신 한국 뉴스 수집."""
    news_items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    ua_headers = {"User-Agent": _BROWSER_UA}

    for source_name, feed_url in NEWS_SOURCES.items():
        if len(news_items) >= count:
            break
        try:
            print(f"  [{source_name}] 수집 중...")
            prev_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(15)
            try:
                feed = feedparser.parse(feed_url, request_headers=ua_headers)
            finally:
                socket.setdefaulttimeout(prev_timeout)

            if not feed.entries:
                continue

            needed = count - len(news_items)
            collected = 0
            for entry in feed.entries:
                if collected >= needed:
                    break
                parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed_time:
                    pub_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", title)).strip()
                summary = re.sub(r"<[^>]+>", "", summary).strip()
                if len(summary) > 300:
                    summary = summary[:297] + "..."
                if not title:
                    continue
                news_items.append({
                    "title": title,
                    "summary": summary,
                    "source": source_name,
                })
                collected += 1

            if collected > 0:
                print(f"  [{source_name}] OK: {collected}개 수집")
        except Exception as e:
            print(f"  [{source_name}] 실패: {e}", file=sys.stderr)

    return news_items[:count]


# ---------------------------------------------------------------------------
# 2. 안건 생성
# ---------------------------------------------------------------------------

def generate_agenda(news_items: list) -> dict:
    """뉴스를 기반으로 이사회 안건을 하나 생성.
    반환: {"title": "...", "description": "...", "news_context": "..."}
    """
    client = anthropic.Anthropic()

    news_block = "\n".join(
        f"{i+1}. [{item['source']}] {item['title']}\n   {item['summary']}"
        for i, item in enumerate(news_items)
    )

    prompt = f"""당신은 '인생 이사회'의 안건 생성 담당입니다.
아래 오늘의 뉴스를 참고하여, 의장(30대 한국인, 가치관: '없으면 만든다')의 인생에 실질적으로 유용한 안건을 하나 만들어주세요.

안건은 다음 중 하나의 카테고리에 해당해야 합니다:
- 커리어/직장: 이직, 승진, 사이드프로젝트, 스킬업
- 재무/투자: 저축, 투자, 부업, 절세
- 건강/웰빙: 운동, 식단, 멘탈관리, 수면
- 관계/소통: 인맥, 커뮤니티, 가족, 연애
- 자기계발: 독서, 학습, 습관, 마인드셋
- 라이프스타일: 주거, 여행, 취미, 일상 최적화

오늘의 뉴스:
{news_block}

뉴스의 트렌드나 이슈에서 영감을 받되, 의장의 일상 인생에 실질적으로 적용할 수 있는 안건으로 만들어주세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"title": "안건 제목 (20자 이내)", "category": "카테고리명", "description": "안건 배경 설명 (뉴스와의 연결점 포함, 100자 이내)", "question": "이사회에서 토론할 핵심 질문 (하나의 명확한 질문)"}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        agenda = json.loads(m.group())
        agenda["news_context"] = news_block
        return agenda

    # 파싱 실패 시 기본 안건
    return {
        "title": "오늘의 자기계발 전략",
        "category": "자기계발",
        "description": "최근 트렌드를 반영한 자기계발 방향 논의",
        "question": "의장님이 이번 주에 시작할 수 있는 가장 효과적인 자기계발 활동은?",
        "news_context": news_block,
    }


# ---------------------------------------------------------------------------
# 3. 이사회 토론 (5명 x 3마디)
# ---------------------------------------------------------------------------

def run_board_discussion(agenda: dict) -> list:
    """각 이사가 안건에 대해 3마디씩 의견을 냄.
    반환: [{"member": {...}, "opinions": ["...", "...", "..."]}, ...]
    """
    client = anthropic.Anthropic()
    discussion = []

    for member in BOARD_MEMBERS:
        prompt = f"""[인생 이사회 안건]
제목: {agenda['title']}
카테고리: {agenda.get('category', '')}
배경: {agenda.get('description', '')}
핵심 질문: {agenda.get('question', '')}

{ALLIANCE_INFO}

당신의 캐릭터:
- 이름: {member['emoji']} {member['name']}
- 관점: {member['perspective']}
- 역할: {member['role']}
- 시그니처: "{member['signature']}"

위 안건에 대해 당신의 캐릭터 관점에서 정확히 3마디 의견을 내세요.
각 의견은 1~2문장으로, 캐릭터의 성격이 분명히 드러나야 합니다.
첫 번째 의견에는 시그니처 문구를 자연스럽게 포함하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"opinions": ["첫 번째 의견", "두 번째 의견", "세 번째 의견"]}}"""

        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=member["system_prompt"],
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                result = json.loads(m.group())
                opinions = result.get("opinions", [])[:3]
            else:
                opinions = [text[:200]]
        except Exception as e:
            print(f"  {member['emoji']} {member['name']} 의견 생성 실패: {e}", file=sys.stderr)
            opinions = [f"({member['name']}: 의견 생성 실패)"]

        discussion.append({
            "member_id": member["id"],
            "name": member["name"],
            "emoji": member["emoji"],
            "opinions": opinions,
        })
        print(f"  {member['emoji']} {member['name']}: {len(opinions)}마디 완료")

    return discussion


# ---------------------------------------------------------------------------
# 4. 선택지 도출 + 투표
# ---------------------------------------------------------------------------

def derive_options_and_vote(agenda: dict, discussion: list) -> dict:
    """토론 내용을 종합하여 선택지를 도출하고 투표를 진행.
    반환: {"options": [...], "votes": {...}, "winner": "...", "summary": "..."}
    """
    client = anthropic.Anthropic()

    # 토론 내용 정리
    discussion_text = ""
    for d in discussion:
        discussion_text += f"\n{d['emoji']} {d['name']}:\n"
        for i, op in enumerate(d["opinions"], 1):
            discussion_text += f"  {i}. {op}\n"

    # 선택지 도출
    options_prompt = f"""[인생 이사회 토론 결과]

안건: {agenda['title']}
핵심 질문: {agenda.get('question', '')}

토론 내용:
{discussion_text}

{ALLIANCE_INFO}

위 토론 내용을 종합하여:
1. 의장이 선택할 수 있는 구체적인 선택지 3개를 도출하세요
2. 각 선택지는 실행 가능한 구체적 행동이어야 합니다
3. 선택지는 서로 다른 방향성을 가져야 합니다 (적극적/균형적/보수적)

반드시 아래 JSON 형식으로만 응답하세요:
{{"options": ["선택지 A (적극적 방향)", "선택지 B (균형적 방향)", "선택지 C (보수적 방향)"]}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": options_prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            options = json.loads(m.group()).get("options", [])[:3]
        else:
            options = ["적극적으로 도전한다", "신중하게 준비한다", "현재 상태를 유지한다"]
    except Exception as e:
        print(f"  선택지 도출 실패: {e}", file=sys.stderr)
        options = ["적극적으로 도전한다", "신중하게 준비한다", "현재 상태를 유지한다"]

    print(f"  선택지 {len(options)}개 도출 완료")

    # 각 이사의 투표
    votes = {}
    options_text = "\n".join(f"  {chr(65+i)}. {opt}" for i, opt in enumerate(options))

    for member in BOARD_MEMBERS:
        # 해당 이사의 이전 발언 찾기
        member_opinions = ""
        for d in discussion:
            if d["member_id"] == member["id"]:
                member_opinions = " / ".join(d["opinions"])
                break

        vote_prompt = f"""[인생 이사회 투표]

안건: {agenda['title']}
핵심 질문: {agenda.get('question', '')}

당신의 이전 발언: {member_opinions}

선택지:
{options_text}

당신의 캐릭터({member['emoji']} {member['name']}, 관점: {member['perspective']})에 맞게
위 선택지 중 하나를 골라 투표하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{"vote": "A", "reason": "투표 이유 (한 줄)"}}"""

        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                system=member["system_prompt"],
                messages=[{"role": "user", "content": vote_prompt}],
            )
            text = message.content[0].text.strip()
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                vote_result = json.loads(m.group())
                vote_letter = vote_result.get("vote", "A").upper().strip()
                if vote_letter not in ["A", "B", "C"]:
                    vote_letter = "A"
                reason = vote_result.get("reason", "")
            else:
                vote_letter = "B"
                reason = ""
        except Exception as e:
            print(f"  {member['emoji']} 투표 실패: {e}", file=sys.stderr)
            vote_letter = "B"
            reason = "(투표 오류)"

        votes[f"{member['emoji']} {member['name']}"] = {
            "vote": vote_letter,
            "option": options[ord(vote_letter) - 65] if ord(vote_letter) - 65 < len(options) else options[0],
            "reason": reason,
        }
        print(f"  {member['emoji']} {member['name']}: {vote_letter} 투표")

    # 결과 집계
    vote_counts = {}
    for v in votes.values():
        letter = v["vote"]
        vote_counts[letter] = vote_counts.get(letter, 0) + 1

    winner_letter = max(vote_counts, key=vote_counts.get)
    winner_idx = ord(winner_letter) - 65
    winner = options[winner_idx] if winner_idx < len(options) else options[0]

    print(f"  투표 결과: {vote_counts} → 채택: {winner_letter}")

    return {
        "options": options,
        "votes": votes,
        "vote_counts": vote_counts,
        "winner_letter": winner_letter,
        "winner": winner,
    }


# ---------------------------------------------------------------------------
# 5. Supabase 저장
# ---------------------------------------------------------------------------

def save_to_supabase(agenda: dict, discussion: list, vote_result: dict, generated_at: datetime) -> bool:
    """Supabase life_council_meetings 테이블에 결과 저장."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        print("경고: SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없습니다.", file=sys.stderr)
        return False

    payload = json.dumps({
        "generated_at": generated_at.isoformat(),
        "agenda": {
            "title": agenda.get("title", ""),
            "category": agenda.get("category", ""),
            "description": agenda.get("description", ""),
            "question": agenda.get("question", ""),
        },
        "discussion": discussion,
        "options": vote_result["options"],
        "votes": vote_result["votes"],
        "vote_counts": vote_result["vote_counts"],
        "winner": vote_result["winner"],
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{url}/rest/v1/life_council_meetings",
        data=payload,
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Supabase 저장 완료 (status: {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Supabase 저장 실패 ({e.code}): {body}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 6. 텔레그램 발송
# ---------------------------------------------------------------------------

def send_to_telegram(agenda: dict, discussion: list, vote_result: dict, generated_at: datetime) -> bool:
    """텔레그램 봇으로 이사회 결과 발송."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("경고: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.", file=sys.stderr)
        return False

    timestamp = generated_at.strftime("%Y년 %m월 %d일 %H:%M")

    # 토론 내용 포맷
    discussion_text = ""
    for d in discussion:
        discussion_text += f"\n{d['emoji']} <b>{d['name']}</b>\n"
        for op in d["opinions"]:
            discussion_text += f"  - {op}\n"

    # 투표 결과 포맷
    options_text = ""
    for i, opt in enumerate(vote_result["options"]):
        letter = chr(65 + i)
        count = vote_result["vote_counts"].get(letter, 0)
        marker = " <b>[채택]</b>" if letter == vote_result["winner_letter"] else ""
        options_text += f"\n{letter}. {opt} ({count}표){marker}"

    # 각 이사 투표 상세
    vote_details = ""
    for name, v in vote_result["votes"].items():
        vote_details += f"\n  {name}: {v['vote']} - {v['reason']}"

    message = (
        f"<b>인생 이사회 회의록</b>  {timestamp}\n"
        f"{'=' * 28}\n\n"
        f"<b>안건: {agenda.get('title', '')}</b>\n"
        f"분야: {agenda.get('category', '')}\n"
        f"{agenda.get('description', '')}\n\n"
        f"<b>핵심 질문</b>\n"
        f"{agenda.get('question', '')}\n\n"
        f"{'—' * 20}\n"
        f"<b>이사회 토론</b>\n"
        f"{discussion_text}\n"
        f"{'—' * 20}\n"
        f"<b>선택지 및 투표 결과</b>\n"
        f"{options_text}\n\n"
        f"<b>투표 상세</b>"
        f"{vote_details}\n\n"
        f"{'=' * 28}\n"
        f"<b>최종 결의: {vote_result['winner']}</b>"
    )

    # 텔레그램 메시지 길이 제한 (4096자)
    if len(message) > 4090:
        message = message[:4087] + "..."

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("텔레그램 발송 완료")
                return True
            else:
                print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 인생 이사회 에이전트 시작 ===\n")

    # [1/5] 뉴스 수집
    print("[1/5] 뉴스 수집 중...")
    news_items = fetch_recent_news(count=5)
    if not news_items:
        print("오류: 뉴스를 수집하지 못했습니다.", file=sys.stderr)
        sys.exit(1)
    print(f"수집 완료: {len(news_items)}개\n")

    # [2/5] 안건 생성
    print("[2/5] 이사회 안건 생성 중...")
    agenda = generate_agenda(news_items)
    print(f"안건: {agenda.get('title', '')} ({agenda.get('category', '')})")
    print(f"질문: {agenda.get('question', '')}\n")

    # [3/5] 이사회 토론
    print("[3/5] 이사회 토론 진행 중 (5명 x 3마디)...")
    discussion = run_board_discussion(agenda)
    print()

    # [4/5] 선택지 도출 + 투표
    print("[4/5] 선택지 도출 및 투표 중...")
    vote_result = derive_options_and_vote(agenda, discussion)
    print(f"최종 결의: {vote_result['winner']}\n")

    generated_at = datetime.now(KST)

    # [5/5] 저장 & 발송
    print("[5/5] 결과 저장 & 발송 중...")
    supabase_ok = save_to_supabase(agenda, discussion, vote_result, generated_at)
    telegram_ok = send_to_telegram(agenda, discussion, vote_result, generated_at)

    print("\n=== 완료 ===")
    print(f"  Supabase: {'OK' if supabase_ok else 'FAIL'}")
    print(f"  Telegram: {'OK' if telegram_ok else 'FAIL'}")

    if not supabase_ok and not telegram_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
