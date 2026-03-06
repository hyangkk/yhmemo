"use client";

import { useEffect, useState, useCallback } from "react";

interface Story {
  id: string;
  title: string;
  original_title: string;
  summary: string;
  emoji: string;
  category: string;
  source: string;
  url: string;
  published_at: string;
  honesty_score: number;
  clickbait_reason: string;
}

interface BriefingResponse {
  stories: Story[];
  total_news_count: number;
  generated_at: string;
  message?: string;
}

interface ChatMessage {
  role: "user" | "ai";
  text: string;
}

function estimateReadTime(text: string): number {
  // 한국어 평균 읽기 속도: 분당 약 500자
  return Math.max(1, Math.ceil(text.length / 500));
}

function getBookmarks(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem("news_bookmarks") || "[]");
  } catch { return []; }
}

function toggleBookmark(storyId: string): string[] {
  const bm = getBookmarks();
  const idx = bm.indexOf(storyId);
  if (idx >= 0) bm.splice(idx, 1);
  else bm.push(storyId);
  localStorage.setItem("news_bookmarks", JSON.stringify(bm));
  return [...bm];
}

export default function MorningBriefing() {
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [completed, setCompleted] = useState(false);
  const [readStories, setReadStories] = useState<Set<number>>(new Set());
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<Record<number, ChatMessage[]>>({});
  const [bookmarks, setBookmarks] = useState<string[]>([]);
  const [newBriefingAvailable, setNewBriefingAvailable] = useState(false);

  // 북마크 로드
  useEffect(() => {
    setBookmarks(getBookmarks());
  }, []);

  const fetchBriefing = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/morning-briefing");
      if (!res.ok) throw new Error("브리핑을 불러올 수 없습니다");
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "오류 발생");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBriefing();
  }, [fetchBriefing]);

  // 30분 후 새 브리핑 알림 (읽는 중 방해하지 않음)
  useEffect(() => {
    const timer = setTimeout(() => {
      setNewBriefingAvailable(true);
    }, 30 * 60 * 1000);
    return () => clearTimeout(timer);
  }, [data]);

  // 키보드 네비게이션
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (chatOpen) return; // 채팅 입력 중에는 무시
      if (e.key === "ArrowRight" || e.key === "j") nextStory();
      if (e.key === "ArrowLeft" || e.key === "k") prevStory();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  });

  const shareStory = async (story: Story) => {
    const text = `${story.emoji} ${story.title}\n${story.summary}\n${story.url}`;
    if (navigator.share) {
      try {
        await navigator.share({ title: story.title, text, url: story.url });
      } catch {
        // 사용자가 취소함
      }
    } else {
      await navigator.clipboard.writeText(text);
      alert("클립보드에 복사되었습니다!");
    }
  };

  const markRead = (index: number) => {
    const newRead = new Set(readStories);
    newRead.add(index);
    setReadStories(newRead);

    if (newRead.size === (data?.stories.length || 5)) {
      setTimeout(() => setCompleted(true), 300);
    }
  };

  const goToStory = (index: number) => {
    setCurrentIndex(index);
    markRead(index);
  };

  const nextStory = () => {
    markRead(currentIndex);
    if (currentIndex < (data?.stories.length || 5) - 1) {
      setCurrentIndex(currentIndex + 1);
      markRead(currentIndex + 1);
    } else {
      setCompleted(true);
    }
  };

  const prevStory = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
    }
  };

  const askQuestion = async (directQuestion?: string) => {
    const q = directQuestion || chatInput.trim();
    if (!q || chatLoading) return;
    const story = data?.stories[currentIndex];
    if (!story) return;

    const question = q;
    setChatInput("");
    setChatMessages((prev) => ({
      ...prev,
      [currentIndex]: [
        ...(prev[currentIndex] || []),
        { role: "user", text: question },
      ],
    }));
    setChatLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          article: {
            title: story.original_title || story.title,
            source: story.source,
            summary: story.summary,
          },
        }),
      });
      const json = await res.json();
      setChatMessages((prev) => ({
        ...prev,
        [currentIndex]: [
          ...(prev[currentIndex] || []),
          { role: "ai", text: json.answer || json.error || "응답 오류" },
        ],
      }));
    } catch {
      setChatMessages((prev) => ({
        ...prev,
        [currentIndex]: [
          ...(prev[currentIndex] || []),
          { role: "ai", text: "네트워크 오류가 발생했습니다." },
        ],
      }));
    } finally {
      setChatLoading(false);
    }
  };

  const resetBriefing = () => {
    setCurrentIndex(0);
    setCompleted(false);
    setReadStories(new Set());
    setChatMessages({});
    setChatOpen(false);
    fetchBriefing();
  };

  if (loading) {
    return (
      <section className="max-w-2xl mx-auto px-4 py-16">
        <div className="text-center mb-8">
          <div className="inline-block w-16 h-16 rounded-2xl bg-gradient-to-br from-amber-400 to-orange-500 animate-pulse mb-4" />
          <p className="text-gray-500 dark:text-gray-400 animate-pulse">
            AI가 오늘의 핵심 뉴스를 고르고 있어요...
          </p>
        </div>
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="h-24 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse"
            />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-2xl mx-auto px-4 py-16 text-center">
        <p className="text-red-500 mb-4">{error}</p>
        <button
          onClick={fetchBriefing}
          className="px-6 py-3 rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition font-medium"
        >
          다시 시도
        </button>
      </section>
    );
  }

  const stories = data?.stories || [];

  if (stories.length === 0) {
    return (
      <section className="max-w-2xl mx-auto px-4 py-16 text-center">
        <div className="text-5xl mb-4">📭</div>
        <p className="text-gray-500 dark:text-gray-400">
          {data?.message || "아직 수집된 뉴스가 없습니다."}
        </p>
      </section>
    );
  }

  // 완료 화면
  if (completed) {
    return (
      <section className="max-w-2xl mx-auto px-4 py-16">
        <div className="text-center py-12">
          <div className="text-7xl mb-6 animate-bounce">✅</div>
          <h2 className="text-3xl font-extrabold text-gray-900 dark:text-white mb-3">
            오늘 뉴스 끝!
          </h2>
          <p className="text-lg text-gray-500 dark:text-gray-400 mb-2">
            {stories.length}개 핵심 뉴스를 모두 확인했어요.
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mb-8">
            {data?.total_news_count}개 뉴스 중 AI가 엄선한{" "}
            {stories.length}개만 읽었습니다.
          </p>

          <div className="flex items-center justify-center gap-3 mb-10">
            <button
              onClick={resetBriefing}
              className="px-6 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-semibold hover:shadow-lg transition-all hover:scale-105"
            >
              새로 브리핑 받기
            </button>
          </div>

          {/* 저장한 뉴스 */}
          {stories.filter(s => bookmarks.includes(s.id)).length > 0 && (
            <div className="text-left space-y-3 mb-8">
              <h3 className="text-sm font-semibold text-amber-500 uppercase tracking-wider mb-4 flex items-center gap-2">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" /></svg>
                저장한 뉴스
              </h3>
              {stories.filter(s => bookmarks.includes(s.id)).map((story, i) => (
                <a
                  key={i}
                  href={story.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/10 hover:bg-amber-100 dark:hover:bg-amber-900/20 transition border border-amber-200 dark:border-amber-800/30"
                >
                  <span className="text-xl">{story.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{story.title}</p>
                    <p className="text-xs text-gray-400">{story.source}</p>
                  </div>
                </a>
              ))}
            </div>
          )}

          {/* 읽은 스토리 요약 */}
          <div className="text-left space-y-3">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
              오늘 읽은 뉴스
            </h3>
            {stories.map((story, i) => (
              <a
                key={i}
                href={story.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 p-3 rounded-xl bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
              >
                <span className="text-xl">{story.emoji}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                    {story.title}
                  </p>
                  <p className="text-xs text-gray-400">{story.source}</p>
                </div>
                <svg
                  className="w-4 h-4 text-gray-300 flex-shrink-0"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                  />
                </svg>
              </a>
            ))}
          </div>
        </div>
      </section>
    );
  }

  // 메인 브리핑 카드 뷰
  const story = stories[currentIndex];

  return (
    <section className="max-w-2xl mx-auto px-4 py-8">
      {/* 새 브리핑 알림 배너 */}
      {newBriefingAvailable && (
        <div className="mb-4 flex items-center justify-between px-4 py-3 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/50 text-sm">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-blue-700 dark:text-blue-300 font-medium">새 브리핑이 준비됐어요!</span>
          </div>
          <button
            onClick={() => { setNewBriefingAvailable(false); resetBriefing(); }}
            className="px-3 py-1 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 transition"
          >
            새로 받기
          </button>
        </div>
      )}
      {/* 프로그레스 바 */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-gray-500 dark:text-gray-400">
            {currentIndex + 1} / {stories.length}
          </span>
          <span className="text-xs text-gray-400">
            {readStories.size}개 읽음
          </span>
        </div>
        <div className="flex gap-1.5">
          {stories.map((_, i) => (
            <button
              key={i}
              onClick={() => goToStory(i)}
              className={`h-1.5 flex-1 rounded-full transition-all duration-300 ${
                i === currentIndex
                  ? "bg-gradient-to-r from-blue-500 to-purple-600"
                  : readStories.has(i)
                    ? "bg-blue-200 dark:bg-blue-800"
                    : "bg-gray-200 dark:bg-gray-700"
              }`}
            />
          ))}
        </div>
      </div>

      {/* 메인 카드 */}
      <article className="relative rounded-2xl border-2 border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 sm:p-8 shadow-sm">
        {/* 카테고리 & 이모지 */}
        <div className="flex items-center gap-3 mb-4">
          <span className="text-3xl">{story.emoji}</span>
          <span className="px-3 py-1 rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 text-xs font-semibold uppercase tracking-wider">
            {story.category}
          </span>
          <span className="text-xs text-gray-400">
            {estimateReadTime(story.summary)}분 읽기
          </span>
          <span className="ml-auto text-xs text-gray-400">
            {story.source}
          </span>
        </div>

        {/* 헤드라인 */}
        <h2 className="text-2xl sm:text-3xl font-extrabold text-gray-900 dark:text-white leading-tight mb-4">
          {story.title}
        </h2>

        {/* AI 요약 */}
        <p className="text-base text-gray-600 dark:text-gray-300 leading-relaxed mb-6">
          {story.summary}
        </p>

        {/* 클릭베이트 킬러 */}
        <div className="p-3 rounded-xl bg-gray-50 dark:bg-gray-800/50 mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500 dark:text-gray-400">
              원본 제목 정직도
            </span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
              story.honesty_score >= 8
                ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                : story.honesty_score >= 5
                  ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                  : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
            }`}>
              {story.honesty_score >= 8 ? "정직" : story.honesty_score >= 5 ? "주의" : "낚시"} {story.honesty_score}/10
            </span>
          </div>
          {/* 바 그래프 */}
          <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mb-2">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                story.honesty_score >= 8
                  ? "bg-green-500"
                  : story.honesty_score >= 5
                    ? "bg-yellow-500"
                    : "bg-red-500"
              }`}
              style={{ width: `${story.honesty_score * 10}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            {story.clickbait_reason}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 italic truncate">
            원본: &quot;{story.original_title}&quot;
          </p>
        </div>

        {/* 원문 링크 + 공유 */}
        <div className="flex items-center gap-4">
          <a
            href={story.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400 hover:underline font-medium"
          >
            원문 보기
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
              />
            </svg>
          </a>
          <button
            onClick={() => shareStory(story)}
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition font-medium"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
            </svg>
            공유
          </button>
          <button
            onClick={() => setBookmarks(toggleBookmark(story.id))}
            className={`inline-flex items-center gap-1.5 text-sm transition font-medium ${
              bookmarks.includes(story.id)
                ? "text-amber-500"
                : "text-gray-500 dark:text-gray-400 hover:text-amber-500"
            }`}
          >
            <svg className="w-4 h-4" fill={bookmarks.includes(story.id) ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            {bookmarks.includes(story.id) ? "저장됨" : "저장"}
          </button>
        </div>
      </article>

      {/* AI 질문하기 */}
      <div className="mt-4">
        <button
          onClick={() => setChatOpen(!chatOpen)}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border-2 border-dashed border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-blue-400 hover:text-blue-500 dark:hover:border-blue-600 dark:hover:text-blue-400 transition-all text-sm font-medium"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          {chatOpen ? "질문 닫기" : "이 뉴스에 질문하기"}
        </button>

        {chatOpen && (
          <div className="mt-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 p-4">
            {/* 채팅 메시지 */}
            {(chatMessages[currentIndex] || []).length > 0 && (
              <div className="space-y-3 mb-4 max-h-60 overflow-y-auto">
                {(chatMessages[currentIndex] || []).map((msg, i) => (
                  <div
                    key={i}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-blue-600 text-white rounded-br-md"
                          : "bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-600 rounded-bl-md"
                      }`}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="px-4 py-2.5 rounded-2xl rounded-bl-md bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600">
                      <div className="flex gap-1">
                        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                        <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* 입력 */}
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") askQuestion(); }}
                placeholder="이 뉴스에 대해 궁금한 점을 물어보세요..."
                className="flex-1 px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                disabled={chatLoading}
              />
              <button
                onClick={() => askQuestion()}
                disabled={chatLoading || !chatInput.trim()}
                className="px-4 py-2.5 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                전송
              </button>
            </div>

            {/* 추천 질문 */}
            {(chatMessages[currentIndex] || []).length === 0 && (
              <div className="flex flex-wrap gap-2 mt-3">
                {[
                  "이게 나에게 어떤 영향이 있어?",
                  "좀 더 쉽게 설명해줘",
                  "관련된 다른 이슈는?",
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => askQuestion(q)}
                    className="px-3 py-1.5 rounded-lg bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 text-xs text-gray-600 dark:text-gray-300 hover:bg-blue-50 dark:hover:bg-blue-900/20 hover:border-blue-300 transition"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 네비게이션 */}
      <div className="flex items-center justify-between mt-6">
        <button
          onClick={prevStory}
          disabled={currentIndex === 0}
          className={`flex items-center gap-2 px-5 py-3 rounded-xl font-medium transition-all ${
            currentIndex === 0
              ? "text-gray-300 dark:text-gray-600 cursor-not-allowed"
              : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
          }`}
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15 19l-7-7 7-7"
            />
          </svg>
          이전
        </button>

        <button
          onClick={nextStory}
          className="flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-semibold hover:shadow-lg transition-all hover:scale-105"
        >
          {currentIndex === stories.length - 1 ? (
            <>
              완료!
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 13l4 4L19 7"
                />
              </svg>
            </>
          ) : (
            <>
              다음
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 5l7 7-7 7"
                />
              </svg>
            </>
          )}
        </button>
      </div>

      {/* 키보드 힌트 */}
      <p className="text-center text-xs text-gray-300 dark:text-gray-600 mt-6">
        <span className="hidden sm:inline">← → 키 또는 J/K 키로 탐색 | </span>
        카드를 넘기며 오늘의 핵심 뉴스를 확인하세요
      </p>
    </section>
  );
}
