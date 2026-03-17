'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface SessionWithResult {
  id: string;
  title: string;
  status: string;
  created_at: string;
  studio_results: { id: string; storage_path: string; duration_ms: number | null; status: string }[];
  studio_clips: { id: string }[];
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}일 전`;
  return new Date(dateStr).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
}

function formatDuration(ms: number | null): string {
  if (!ms) return '';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toString().padStart(2, '0')}`;
}

export default function RecentSessions() {
  const [sessions, setSessions] = useState<SessionWithResult[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await fetch('/api/studio/sessions/recent');
        if (res.ok) {
          const data = await res.json();
          setSessions(data || []);
        }
      } catch {}
      setLoading(false);
    }
    load();
  }, []);

  if (loading) return null;
  if (sessions.length === 0) return null;

  return (
    <section className="max-w-5xl mx-auto px-4 pb-12">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="text-xl">🎬</span>
          최근 촬영
        </h2>
        <Link
          href="/studio"
          className="text-sm text-violet-600 dark:text-violet-400 hover:underline font-medium"
        >
          새 촬영 +
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {sessions.map((sess) => {
          const doneResults = sess.studio_results?.filter(r => r.status === 'done') || [];
          const latestResult = doneResults.sort((a, b) =>
            b.storage_path.localeCompare(a.storage_path)
          )[0];
          const clipCount = sess.studio_clips?.length || 0;
          const isEditing = sess.status === 'editing';

          return (
            <Link
              key={sess.id}
              href={`/studio/${sess.id}/result`}
              className="group block"
            >
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 hover:shadow-lg hover:border-violet-300 dark:hover:border-violet-700 transition-all">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white truncate flex-1">
                    {sess.title}
                  </h3>
                  {isEditing ? (
                    <span className="shrink-0 flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 text-[11px] font-medium">
                      <span className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
                      편집 중
                    </span>
                  ) : doneResults.length > 0 ? (
                    <span className="shrink-0 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 text-[11px] font-medium">
                      {doneResults.length}개 결과
                    </span>
                  ) : (
                    <span className="shrink-0 px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 text-[11px] font-medium">
                      완료
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2 mt-2 text-xs text-gray-500 dark:text-gray-400">
                  <span>{clipCount}클립</span>
                  {latestResult?.duration_ms && (
                    <>
                      <span className="text-gray-300 dark:text-gray-600">·</span>
                      <span>{formatDuration(latestResult.duration_ms)}</span>
                    </>
                  )}
                  <span className="text-gray-300 dark:text-gray-600">·</span>
                  <span>{formatRelativeTime(sess.created_at)}</span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
