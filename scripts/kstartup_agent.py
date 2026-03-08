#!/usr/bin/env python3
"""
K-Startup 사업공고 모니터링 에이전트
- 매일 오전 9시(KST) GitHub Actions에 의해 자동 실행
- K-Startup 진행 중 사업공고 목록 수집
- 새 공고 발견 시: PDF 다운로드 → 자격요건 분석 → 프로필 대조
- 지원 가능한 공고는 신청 서류 초안까지 작성
- 결과를 Supabase 저장 + 텔레그램 발송

Supabase 필요 테이블:
  - user_profile      : 기업/개인 프로필 (id=1 고정)
  - kstartup_announcements : 처리된 공고 기록
"""

import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from io import BytesIO

import requests
from bs4 import BeautifulSoup
import pypdf
import anthropic

KST = timezone(timedelta(hours=9))

KSTARTUP_BASE = "https://www.k-startup.go.kr"
KSTARTUP_LIST_URL = f"{KSTARTUP_BASE}/web/contents/bizpbanc-ongoing.do"
KSTARTUP_OPEN_API_URL = (
    "https://apis.data.go.kr/B552735/kisedKstartupService01"
    "/getAnnouncementInformation01"
)

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": KSTARTUP_LIST_URL,
}


# ---------------------------------------------------------------------------
# Supabase 공통
# ---------------------------------------------------------------------------

def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _supabase_get(path: str) -> list:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return []
    req = urllib.request.Request(f"{url}{path}", headers=_supabase_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Supabase GET 실패 ({path}): {e}", file=sys.stderr)
        return []


def _supabase_post(path: str, data: dict) -> bool:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return False
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{url}{path}",
        data=payload,
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        print(f"Supabase POST 실패 ({e.code}): {e.read().decode()}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 0. 에이전트 설정 로드
# ---------------------------------------------------------------------------

def fetch_settings() -> dict:
    """Supabase agent_settings(id=1)에서 K-Startup 설정 로드."""
    default = {"kstartup_enabled": True, "kstartup_run_every_hours": 24, "kstartup_keywords": ""}
    rows = _supabase_get("/rest/v1/agent_settings?id=eq.1")
    if rows:
        s = rows[0]
        return {
            "kstartup_enabled": s.get("kstartup_enabled", True),
            "kstartup_run_every_hours": int(s.get("kstartup_run_every_hours", 24)),
            "kstartup_keywords": s.get("kstartup_keywords", "") or "",
        }
    return default


# ---------------------------------------------------------------------------
# 1. 사용자 프로필 로드
# ---------------------------------------------------------------------------

def sort_by_keywords(announcements: list, keywords_str: str) -> list:
    """keywords_str(쉼표 구분)에 해당하는 공고를 앞으로 정렬. 키워드 없으면 원래 순서 유지."""
    if not keywords_str or not keywords_str.strip():
        return announcements
    keywords = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
    if not keywords:
        return announcements

    def score(ann: dict) -> int:
        text = (ann.get("title", "") + " " + ann.get("api_content", "")).lower()
        return sum(1 for kw in keywords if kw in text)

    matched = [a for a in announcements if score(a) > 0]
    unmatched = [a for a in announcements if score(a) == 0]
    matched.sort(key=score, reverse=True)
    print(f"  키워드 매칭: {len(matched)}개 우선 / 나머지 {len(unmatched)}개")
    return matched + unmatched


def load_user_profile() -> dict:
    """Supabase user_profile 테이블(id=1)에서 사용자 프로필 로드."""
    rows = _supabase_get("/rest/v1/user_profile?id=eq.1")
    if rows:
        print(f"  프로필 로드: {rows[0].get('company_name', '(이름 없음)')}")
        return rows[0]
    print("  경고: user_profile 테이블에 데이터 없음. Supabase에서 설정 필요.", file=sys.stderr)
    return {}


# ---------------------------------------------------------------------------
# 2. 처리된 공고 ID 로드
# ---------------------------------------------------------------------------

def get_seen_ids() -> set:
    """이미 처리한 공고 ID 목록."""
    rows = _supabase_get("/rest/v1/kstartup_announcements?select=announcement_id")
    return {r["announcement_id"] for r in rows}


# ---------------------------------------------------------------------------
# 3. K-Startup 공고 목록 수집 (공공데이터포털 공식 API)
# ---------------------------------------------------------------------------

def fetch_announcements(seen_ids: set = None, max_new: int = 10) -> list:
    """공공데이터포털 공식 API로 K-Startup 진행 중 사업공고 수집.

    seen_ids에 없는 신규 공고만 수집하며, max_new개 도달 시 즉시 중단.
    """
    if seen_ids is None:
        seen_ids = set()
    api_key = os.environ.get("KSTARTUP_API_KEY", "")
    if not api_key:
        print("  오류: KSTARTUP_API_KEY 환경 변수가 없습니다.", file=sys.stderr)
        return []

    results = []
    page = 1
    per_page = 100

    while page <= 5:  # 최대 500개 조회
        params = {
            "serviceKey": api_key,
            "page": str(page),
            "perPage": str(per_page),
            "returnType": "json",
        }
        try:
            resp = requests.get(KSTARTUP_OPEN_API_URL, params=params, timeout=30)
            print(f"  API 페이지 {page} → status {resp.status_code}, size {len(resp.content)}B")
            if resp.status_code != 200:
                print(f"  API 오류 응답: {resp.text[:200]}", file=sys.stderr)
                break

            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                if item.get("rcrt_prgs_yn") != "Y":
                    continue
                ann_id = str(item.get("pbanc_sn", ""))
                if not ann_id or ann_id in seen_ids:
                    continue

                # 마감일 YYYYMMDD → YYYY-MM-DD
                raw_dl = item.get("pbanc_rcpt_end_dt", "")
                deadline = (
                    f"{raw_dl[:4]}-{raw_dl[4:6]}-{raw_dl[6:]}"
                    if raw_dl and len(raw_dl) == 8 else raw_dl
                )

                detail_url = item.get("detl_pg_url") or f"{KSTARTUP_LIST_URL}?pbancSn={ann_id}"

                results.append({
                    "announcement_id": ann_id,
                    "title": item.get("biz_pbanc_nm", "").strip(),
                    "url": detail_url,
                    "deadline": deadline,
                    "api_content": _build_api_content(item),
                })

                if len(results) >= max_new:
                    print(f"  신규 공고 {max_new}개 도달 — 수집 중단")
                    return results

            total = data.get("totalCount", 0)
            if page * per_page >= total:
                break
            page += 1

        except Exception as e:
            print(f"  API 호출 실패 (page {page}): {e}", file=sys.stderr)
            break

    print(f"  신규 공고 {len(results)}개 수집 완료")
    return results


def _build_api_content(item: dict) -> str:
    """API 응답 항목에서 공고 내용 텍스트 구성."""
    parts = []
    if item.get("supt_biz_clsfc"):
        parts.append(f"지원 분류: {item['supt_biz_clsfc']}")
    if item.get("supt_regin"):
        parts.append(f"지원 지역: {item['supt_regin']}")
    if item.get("aply_trgt"):
        parts.append(f"신청 대상: {item['aply_trgt']}")
    if item.get("aply_trgt_ctnt"):
        parts.append(f"신청 자격:\n{item['aply_trgt_ctnt'][:2000]}")
    if item.get("aply_excl_trgt_ctnt"):
        parts.append(f"신청 제외 대상:\n{item['aply_excl_trgt_ctnt'][:1000]}")
    if item.get("pbanc_ctnt"):
        parts.append(f"공고 내용:\n{item['pbanc_ctnt'][:2000]}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 4. 공고 상세 페이지 수집
# ---------------------------------------------------------------------------

def fetch_announcement_detail(url: str) -> dict:
    """공고 상세 페이지에서 내용 텍스트 및 첨부파일 링크 추출."""
    result = {"content": "", "pdf_urls": [], "apply_urls": []}

    try:
        resp = requests.get(url, headers=SESSION_HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        # 본문 텍스트
        body = soup.find(class_=re.compile(r"view|content|detail|body", re.I))
        if body:
            result["content"] = body.get_text(separator="\n", strip=True)[:5000]

        # 첨부파일 링크
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)

            is_file = (
                ".pdf" in href.lower() or
                "fileDown" in href or
                "download" in href.lower() or
                "atchFile" in href or
                ".hwp" in href.lower()
            )
            if not is_file:
                continue

            full_url = href if href.startswith("http") else f"{KSTARTUP_BASE}{href}"

            apply_keywords = ["신청서", "서식", "양식", "지원서", "신청양식", "서류"]
            if any(kw in text for kw in apply_keywords):
                result["apply_urls"].append({"url": full_url, "name": text})
            else:
                result["pdf_urls"].append({"url": full_url, "name": text})

    except Exception as e:
        print(f"  상세 페이지 가져오기 실패 ({url}): {e}", file=sys.stderr)

    return result


# ---------------------------------------------------------------------------
# 5. PDF/HWP 텍스트 추출
# ---------------------------------------------------------------------------

def download_and_extract_text(url: str) -> str:
    """PDF 파일 다운로드 후 텍스트 추출. HWP는 텍스트 추출 불가로 건너뜀."""
    if ".hwp" in url.lower():
        return ""  # HWP는 별도 파서 필요 — 현재 미지원

    try:
        resp = requests.get(url, headers=SESSION_HEADERS, timeout=60)
        if resp.status_code != 200:
            return ""

        reader = pypdf.PdfReader(BytesIO(resp.content))
        pages = []
        for page in reader.pages[:20]:
            text = page.extract_text() or ""
            pages.append(text)

        return "\n".join(pages)[:8000]

    except Exception as e:
        print(f"  PDF 추출 실패 ({url[:60]}): {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# 6. Claude 적합성 분석
# ---------------------------------------------------------------------------

def analyze_eligibility(
    announcement: dict,
    pdf_text: str,
    page_content: str,
    user_profile: dict,
) -> dict:
    """Claude로 자격요건 분석 및 기업 프로필과 적합성 판단."""
    client = anthropic.Anthropic()

    profile_text = json.dumps(user_profile, ensure_ascii=False, indent=2)
    content = (pdf_text or page_content or "공고 내용을 가져오지 못했습니다.")[:6000]

    prompt = f"""당신은 창업 지원 사업 전문가입니다.
아래의 사업공고 내용을 분석하여, 주어진 기업 프로필이 지원 자격을 갖추고 있는지 판단해주세요.

## 사업 공고명
{announcement['title']}

## 기업 프로필
{profile_text}

## 공고 내용
{content}

## 분석 요청
1. 핵심 지원 자격 요건을 3~5개 추출하세요.
2. 기업 프로필의 각 요건 충족 여부를 판단하세요 (충족/미충족/불명확).
3. 종합적인 지원 가능 여부를 판단하세요.
4. 한 줄 요약을 작성하세요.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "requirements": [
    {{"condition": "요건 설명", "status": "충족", "reason": "판단 근거"}}
  ],
  "eligible": true,
  "summary": "최종 판단 한 줄 요약"
}}

eligible 값: true(지원 가능), false(지원 불가), null(정보 부족으로 불명확)"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()

        # JSON 파싱
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group())
        return {"eligible": None, "summary": text[:300], "requirements": []}

    except Exception as e:
        print(f"  적합성 분석 오류: {e}", file=sys.stderr)
        return {"eligible": None, "summary": f"분석 오류: {e}", "requirements": []}


# ---------------------------------------------------------------------------
# 7. Claude 신청서 초안 작성
# ---------------------------------------------------------------------------

def draft_application(
    announcement: dict,
    apply_text: str,
    pdf_text: str,
    user_profile: dict,
) -> str:
    """적합한 공고에 대해 Claude로 신청서 초안 작성."""
    client = anthropic.Anthropic()

    profile_text = json.dumps(user_profile, ensure_ascii=False, indent=2)

    prompt = f"""당신은 창업 지원 사업 신청서 작성 전문가입니다.
아래 정보를 바탕으로 신청서 초안을 마크다운 형식으로 작성해주세요.
실제 데이터가 없는 항목은 [확인 필요: 항목명] 형태로 표시하세요.

## 공고명
{announcement['title']}

## 기업 프로필
{profile_text}

## 사업 개요 (공고 PDF 요약)
{pdf_text[:2500] if pdf_text else "(공고 PDF 없음)"}

## 신청 양식 내용
{apply_text[:2500] if apply_text else "(양식 파일 없음 - 일반 창업지원 신청서 형식으로 작성)"}

---

다음 항목을 모두 포함한 신청서 초안을 작성하세요:

# 사업 신청서 초안 — {announcement['title']}

## 1. 신청 기업 현황
(기업명, 설립일, 업종, 주요 제품/서비스, 대표자 등)

## 2. 신청 목적 및 사업 이해도
(이 사업에 지원하는 이유, 사업 목표와의 연관성)

## 3. 지원금/프로그램 활용 계획
(구체적인 활용 방안, 일정 등)

## 4. 기대 효과
(정량적/정성적 기대 성과)

## 5. 향후 성장 계획
(중장기 발전 방향)"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        print(f"  초안 작성 오류: {e}", file=sys.stderr)
        return f"초안 작성 실패: {e}"


# ---------------------------------------------------------------------------
# 8. Supabase 저장
# ---------------------------------------------------------------------------

def save_announcement(announcement: dict, analysis: dict, draft: str = "") -> bool:
    return _supabase_post(
        "/rest/v1/kstartup_announcements",
        {
            "announcement_id": announcement["announcement_id"],
            "title": announcement["title"],
            "url": announcement["url"],
            "deadline": announcement.get("deadline", ""),
            "eligible": analysis.get("eligible"),
            "analysis": json.dumps(analysis, ensure_ascii=False),
            "draft": draft,
            "created_at": datetime.now(KST).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# 9. 텔레그램 알림
# ---------------------------------------------------------------------------

def send_telegram(
    token: str,
    chat_id: str,
    announcement: dict,
    analysis: dict,
    draft: str = "",
) -> bool:
    eligible = analysis.get("eligible")
    if eligible is True:
        status = "✅ 지원 가능"
    elif eligible is False:
        status = "❌ 지원 불가"
    else:
        status = "❓ 검토 필요"

    summary = analysis.get("summary", "")[:300]
    reqs = analysis.get("requirements", [])

    req_lines = ""
    for r in reqs[:4]:
        icon = {"충족": "✅", "미충족": "❌"}.get(r.get("status", ""), "❓")
        req_lines += f"{icon} {r.get('condition', '')[:50]}\n"

    msg = (
        f"<b>📢 K-Startup 새 공고</b>\n\n"
        f"<b>사업명:</b> {announcement['title'][:80]}\n"
        f"<b>마감:</b> {announcement.get('deadline', '미상')}\n"
        f"<b>링크:</b> {announcement['url']}\n\n"
        f"<b>적합성:</b> {status}\n"
        f"<b>요약:</b> {summary}\n"
    )
    if req_lines:
        msg += f"\n<b>자격 요건:</b>\n{req_lines}"
    if draft:
        msg += f"\n<b>📝 신청서 초안 작성 완료</b> (Supabase 저장됨)\n"

    payload = json.dumps({
        "chat_id": chat_id,
        "text": msg,
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("  텔레그램 발송 완료")
                return True
            print(f"  텔레그램 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  텔레그램 오류: {e}", file=sys.stderr)
        return False


def send_telegram_summary(token: str, chat_id: str, message: str) -> None:
    """간단한 요약 메시지를 텔레그램으로 발송."""
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("  텔레그램 요약 발송 완료")
            else:
                print(f"  텔레그램 요약 실패: {result}", file=sys.stderr)
    except Exception as e:
        print(f"  텔레그램 요약 오류: {e}", file=sys.stderr)




def main():
    print("=== K-Startup 사업공고 모니터링 에이전트 시작 ===\n")

    # 0. 설정 로드 및 실행 여부 판단
    settings = fetch_settings()
    if not settings["kstartup_enabled"]:
        print("K-Startup 에이전트가 비활성화되어 있습니다. 종료합니다.")
        return

    run_every = settings["kstartup_run_every_hours"]
    kstartup_keywords = settings.get("kstartup_keywords", "")
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if run_every > 1 and not is_manual:
        current_hour_utc = datetime.now(timezone.utc).hour
        if current_hour_utc % run_every != 0:
            print(f"현재 {current_hour_utc}시 (UTC) — {run_every}시간 간격 미해당. 건너뜀.")
            return
    if is_manual:
        print("수동 실행 — 시간 간격 체크 건너뜀.")
    print(f"실행 주기: {run_every}시간\n")

    # 1. 사용자 프로필
    print("[1/5] 사용자 프로필 로드 중...")
    user_profile = load_user_profile()
    if not user_profile:
        print("  경고: 프로필 없이 계속 진행합니다. 적합성 분석이 부정확할 수 있습니다.")

    # 2. 기존 처리 공고 ID
    print("\n[2/5] 기존 공고 목록 로드 중...")
    seen_ids = get_seen_ids()
    print(f"  기존 처리 공고: {len(seen_ids)}개")

    # 3. 새 공고 수집 (최대 10개, seen_ids 제외하며 조기 중단)
    print("\n[3/5] K-Startup 사업공고 수집 중...")
    new_anns = fetch_announcements(seen_ids=seen_ids, max_new=10)
    new_anns = sort_by_keywords(new_anns, kstartup_keywords)
    print(f"  새 공고: {len(new_anns)}개")

    # 4. 텔레그램 토큰 설정
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not new_anns and not seen_ids:
        msg = (
            f"<b>📢 K-Startup 모니터링 결과</b>\n\n"
            f"⚠️ 공식 API에서 공고를 수집하지 못했습니다.\n"
            f"KSTARTUP_API_KEY 확인 또는 일시적 API 오류일 수 있습니다."
        )
        if token and chat_id:
            send_telegram_summary(token, chat_id, msg)
        print("\nK-Startup에서 공고를 가져오지 못했습니다. 종료합니다.")
        return

    if not new_anns:
        msg = (
            f"<b>📢 K-Startup 모니터링 결과</b>\n\n"
            f"✅ 에이전트 정상 실행 완료\n"
            f"새 공고: 0개 (모두 이미 처리된 공고입니다)"
        )
        if token and chat_id:
            send_telegram_summary(token, chat_id, msg)
        print("\n새로운 공고가 없습니다. 종료합니다.")
        return

    print(f"\n[4/5] 새 공고 {len(new_anns)}개 분석 중...")

    eligible_count = 0
    for i, ann in enumerate(new_anns, 1):
        print(f"\n  [{i}/{len(new_anns)}] {ann['title'][:60]}...")

        # 상세 페이지
        detail = fetch_announcement_detail(ann["url"])

        # PDF 텍스트 수집 (공고문, 최대 2개)
        pdf_text = ""
        for pdf_info in detail["pdf_urls"][:2]:
            print(f"    PDF 다운로드: {pdf_info['name'][:40]}")
            t = download_and_extract_text(pdf_info["url"])
            if t:
                pdf_text += t + "\n\n"

        # 적합성 분석 (API 내용 + 상세페이지 내용 + PDF 순으로 우선)
        page_content = detail["content"] or ann.get("api_content", "")
        print("    적합성 분석 중...")
        analysis = analyze_eligibility(ann, pdf_text, page_content, user_profile)
        eligible = analysis.get("eligible")
        label = "지원 가능 ✅" if eligible is True else "지원 불가 ❌" if eligible is False else "검토 필요 ❓"
        print(f"    결과: {label}")

        # 신청서 초안 (적합한 경우)
        draft = ""
        if eligible is True:
            eligible_count += 1
            print("    신청서 초안 작성 중...")
            apply_text = ""
            for apply_info in detail["apply_urls"][:1]:
                apply_text = download_and_extract_text(apply_info["url"])
            draft = draft_application(ann, apply_text, pdf_text, user_profile)

        # 저장 & 알림
        save_announcement(ann, analysis, draft)
        if token and chat_id:
            send_telegram(token, chat_id, ann, analysis, draft)

        if i < len(new_anns):
            time.sleep(2)

    print(f"\n[5/5] 완료")
    print(f"  처리: {len(new_anns)}개 | 지원 가능: {eligible_count}개")

    if token and chat_id:
        summary_msg = (
            f"<b>📊 K-Startup 분석 완료</b>\n\n"
            f"새 공고: {len(new_anns)}개 처리\n"
            f"지원 가능: {eligible_count}개"
        )
        send_telegram_summary(token, chat_id, summary_msg)


if __name__ == "__main__":
    main()
