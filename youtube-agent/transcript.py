"""
YouTube 트랜스크립트(자막) 추출 및 요약 모듈
"""

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# YouTube URL 패턴
_YT_PATTERNS = [
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})'),
    re.compile(r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})'),
]

# Slack URL 형식: <https://...|표시텍스트> 또는 <https://...>
_SLACK_URL_PATTERN = re.compile(r'<(https?://[^|>]+)(?:\|[^>]*)?>')


def extract_video_id(text: str) -> Optional[str]:
    """텍스트에서 YouTube 비디오 ID 추출"""
    slack_urls = _SLACK_URL_PATTERN.findall(text)
    candidates = slack_urls + [text]
    for candidate in candidates:
        for pattern in _YT_PATTERNS:
            match = pattern.search(candidate)
            if match:
                return match.group(1)
    return None


def has_youtube_url(text: str) -> bool:
    """텍스트에 YouTube URL이 포함되어 있는지 확인"""
    return extract_video_id(text) is not None


async def fetch_transcript(video_id: str, languages: list[str] = None) -> dict:
    """YouTube 자막 추출

    Returns:
        {"ok": True, "text": "...", "segments": [...], "language": "ko"}
        or {"ok": False, "error": "에러 메시지"}
    """
    if languages is None:
        languages = ["ko", "en", "ja"]

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled,
            NoTranscriptFound,
            VideoUnavailable,
        )
    except ImportError:
        return {"ok": False, "error": "youtube-transcript-api 패키지가 설치되어 있지 않습니다."}

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=languages)

        segments = []
        full_text_parts = []
        for entry in transcript.snippets:
            segments.append({
                "start": entry.start,
                "duration": entry.duration,
                "text": entry.text,
            })
            full_text_parts.append(entry.text)

        full_text = " ".join(full_text_parts)
        lang = transcript.language_code if hasattr(transcript, 'language_code') else languages[0]

        return {
            "ok": True,
            "text": full_text,
            "segments": segments,
            "language": lang,
            "video_id": video_id,
        }

    except TranscriptsDisabled:
        return {"ok": False, "error": "이 영상은 자막이 비활성화되어 있습니다."}
    except NoTranscriptFound:
        try:
            transcript_list = ytt_api.list(video_id)
            for t in transcript_list:
                if t.is_generated:
                    transcript = ytt_api.fetch(video_id, languages=[t.language_code])
                    segments = []
                    full_text_parts = []
                    for entry in transcript.snippets:
                        segments.append({
                            "start": entry.start,
                            "duration": entry.duration,
                            "text": entry.text,
                        })
                        full_text_parts.append(entry.text)
                    return {
                        "ok": True,
                        "text": " ".join(full_text_parts),
                        "segments": segments,
                        "language": t.language_code,
                        "video_id": video_id,
                        "auto_generated": True,
                    }
            return {"ok": False, "error": f"자막을 찾을 수 없습니다. (지원 언어: {', '.join(languages)})"}
        except Exception:
            return {"ok": False, "error": f"자막을 찾을 수 없습니다. (지원 언어: {', '.join(languages)})"}
    except VideoUnavailable:
        return {"ok": False, "error": "영상을 찾을 수 없거나 비공개 영상입니다."}
    except Exception as e:
        logger.error(f"Transcript fetch error for {video_id}: {e}")
        return {"ok": False, "error": f"자막 추출 실패: {str(e)[:200]}"}


async def fetch_video_info(video_id: str) -> dict:
    """YouTube 영상 기본 정보 (제목 등) - oembed API"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "title": data.get("title", ""),
                    "author": data.get("author_name", ""),
                }
    except Exception as e:
        logger.debug(f"Video info fetch error: {e}")
    return {"title": "", "author": ""}


async def summarize_transcript(ai_client, transcript_text: str, video_title: str = "",
                                mode: str = "summary") -> str:
    """Claude로 트랜스크립트 요약

    Args:
        ai_client: anthropic.AsyncAnthropic 인스턴스
        transcript_text: 전체 자막 텍스트
        video_title: 영상 제목
        mode: "summary" | "full" | "key_points" | "qna"
    """
    max_chars = 300_000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars] + "\n\n... (자막이 너무 길어 일부만 포함)"

    title_hint = f"\n영상 제목: {video_title}" if video_title else ""

    prompts = {
        "summary": f"""다음은 YouTube 영상의 자막입니다.{title_hint}

이 영상의 내용을 한국어로 요약해주세요.

요약 형식:
1. **핵심 주제** (1-2줄)
2. **주요 내용** (핵심 포인트 3-7개, 불릿)
3. **결론/시사점** (1-2줄)

자막:
{transcript_text}""",

        "full": f"""다음은 YouTube 영상의 자막입니다.{title_hint}

이 자막을 깔끔하게 정리해주세요:
- 말의 반복, 군더더기를 제거
- 주제별로 구분
- 읽기 쉽게 문단 나누기
- 한국어로 작성 (원문이 영어면 번역)

자막:
{transcript_text}""",

        "key_points": f"""다음은 YouTube 영상의 자막입니다.{title_hint}

핵심 포인트만 추출해주세요:
- 가장 중요한 인사이트 5-10개
- 각 포인트는 1-2줄로 간결하게
- 실행 가능한 조언이 있다면 별도 표시

자막:
{transcript_text}""",
    }

    user_prompt = prompts.get(mode, prompts["summary"])

    response = await ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system="당신은 영상 내용을 정확하고 깊이있게 요약하는 전문가입니다. 슬랙 메시지에 적합한 포맷으로 작성하세요.",
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


async def answer_about_video(ai_client, transcript_text: str, question: str,
                              video_title: str = "") -> str:
    """영상 내용에 대한 질문에 답변"""
    max_chars = 300_000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars]

    title_hint = f" ({video_title})" if video_title else ""

    response = await ai_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=3000,
        system=f"당신은 YouTube 영상{title_hint}의 내용을 완벽히 이해한 전문가입니다. 자막 내용을 바탕으로 질문에 정확하게 답변하세요. 자막에 없는 내용은 '영상에서 다루지 않은 내용'이라고 명시하세요.",
        messages=[{"role": "user", "content": f"[영상 자막]\n{transcript_text}\n\n[질문]\n{question}"}],
    )
    return response.content[0].text
