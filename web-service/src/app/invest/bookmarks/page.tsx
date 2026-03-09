"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface BookmarkedStory {
  id: string;
  title: string;
  emoji: string;
  summary: string;
  source: string;
  url: string;
  category: string;
}

function getBookmarks(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem("news_bookmarks") || "[]");
  } catch {
    return [];
  }
}

function removeBookmark(storyId: string): string[] {
  const bm = getBookmarks().filter((id) => id !== storyId);
  localStorage.setItem("news_bookmarks", JSON.stringify(bm));
  return bm;
}

export default function BookmarksPage() {
  const [bookmarkIds, setBookmarkIds] = useState<string[]>([]);
  const [stories, setStories] = useState<BookmarkedStory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ids = getBookmarks();
    setBookmarkIds(ids);

    if (ids.length === 0) {
      setLoading(false);
      return;
    }

    fetch("/api/morning-briefing")
      .then((res) => res.json())
      .then((data) => {
        const matched = (data.stories || []).filter(
          (s: BookmarkedStory) => ids.includes(s.id)
        );
        setStories(matched);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleRemove = (storyId: string) => {
    const updated = removeBookmark(storyId);
    setBookmarkIds(updated);
    setStories((prev) => prev.filter((s) => s.id !== storyId));
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      <div className="max-w-2xl mx-auto px-4 py-12">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <Link
              href="/invest"
              className="text-sm text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition mb-2 inline-block"
            >
              &larr; 투자전략실
            </Link>
            <h1 className="text-3xl font-extrabold text-gray-900 dark:text-white flex items-center gap-3">
              <svg
                className="w-8 h-8 text-amber-500"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
              저장한 뉴스
            </h1>
          </div>
          <span className="text-sm text-gray-400">
            {bookmarkIds.length}개 저장됨
          </span>
        </div>

        {loading ? (
          <div className="space-y-4">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="h-24 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse"
              />
            ))}
          </div>
        ) : stories.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">📑</div>
            <p className="text-gray-500 dark:text-gray-400 mb-2">
              저장한 뉴스가 없습니다
            </p>
            <p className="text-sm text-gray-400 dark:text-gray-500 mb-6">
              뉴스 카드에서 저장 버튼을 눌러 관심 뉴스를 모아보세요
            </p>
            <Link
              href="/invest"
              className="inline-flex px-6 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-semibold hover:shadow-lg transition-all hover:scale-105"
            >
              브리핑 보러 가기
            </Link>
          </div>
        ) : (
          <div className="space-y-4">
            {stories.map((story) => (
              <div
                key={story.id}
                className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 hover:shadow-md transition-all"
              >
                <div className="flex items-start gap-4">
                  <span className="text-2xl mt-0.5">{story.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 text-xs font-semibold">
                        {story.category}
                      </span>
                      <span className="text-xs text-gray-400">
                        {story.source}
                      </span>
                    </div>
                    <h3 className="font-bold text-gray-900 dark:text-white mb-2">
                      {story.title}
                    </h3>
                    <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed line-clamp-2">
                      {story.summary}
                    </p>
                    <div className="flex items-center gap-4 mt-3">
                      <a
                        href={story.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm text-blue-600 dark:text-blue-400 hover:underline font-medium"
                      >
                        원문 보기 &rarr;
                      </a>
                      <button
                        onClick={() => handleRemove(story.id)}
                        className="text-sm text-red-400 hover:text-red-600 transition font-medium"
                      >
                        삭제
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
