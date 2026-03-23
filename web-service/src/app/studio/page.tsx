'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';

type Mode = 'multicam' | 'timeline';

interface RecentSession {
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
  return `${Math.floor(hours / 24)}일 전`;
}

export default function StudioPage() {
  const router = useRouter();
  const { user, signInWithGoogle } = useAuth();
  const [mode, setMode] = useState<Mode>('multicam');
  const [title, setTitle] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState<{ front: string; server: string } | null>(null);
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);

  const isSupaCam = typeof window !== 'undefined' && window.location.hostname.includes('supacam');

  useEffect(() => {
    fetch('/api/studio/version').then(r => r.json()).then(setVersion).catch(() => {});
    fetch('/api/studio/sessions/recent').then(r => r.json()).then(setRecentSessions).catch(() => {});
  }, []);

  const createSession = async () => {
    setLoading(true);
    setError('');
    try {
      const defaultTitle = mode === 'multicam' ? '멀티캠 촬영' : '타임라인 촬영';
      const res = await fetch('/api/studio/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title || defaultTitle }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      router.push(`/studio/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '세션 생성 실패');
    } finally {
      setLoading(false);
    }
  };

  const joinSession = async () => {
    if (!joinCode.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`/api/studio/sessions?code=${joinCode.trim()}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      router.push(`/studio/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '세션을 찾을 수 없습니다');
    } finally {
      setLoading(false);
    }
  };

  const handleProfileClick = () => {
    if (user) {
      router.push('/mypage');
    } else {
      signInWithGoogle();
    }
  };

  return (
    <div className={`min-h-screen bg-black text-white flex flex-col items-center p-4 ${recentSessions.length > 0 ? 'pt-12' : 'justify-center'}`}>
      {/* 우측 상단 버튼 */}
      <div className="fixed top-4 right-4 z-50 flex items-center gap-2">
        {user && (
          <button
            onClick={handleProfileClick}
            className="flex items-center gap-1.5 bg-gray-900 hover:bg-gray-800 border border-gray-700 px-3 py-2 rounded-xl text-sm transition cursor-pointer"
          >
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="" className="w-5 h-5 rounded-full" />
            ) : (
              <span className="w-5 h-5 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">
                {user.name?.charAt(0) || 'U'}
              </span>
            )}
            <span className="text-gray-300">{user.name}</span>
          </button>
        )}
        {!(isSupaCam && user) && (
          <button
            onClick={() => user ? router.push('/projects') : signInWithGoogle()}
            className="bg-gray-900 hover:bg-gray-800 border border-gray-700 px-3 py-2 rounded-xl text-sm transition cursor-pointer"
          >
            <span className="text-gray-300">{user ? '프로젝트' : '로그인'}</span>
          </button>
        )}
      </div>

      <div className="max-w-sm w-full space-y-4">
        {/* 타이틀 */}
        <div className="text-center pb-2">
          <h1 className="text-2xl font-bold">SupaCam 슈파캠</h1>
          <p className="text-gray-500 text-xs mt-1">여러 카메라로 촬영 · AI 자동 편집</p>
        </div>

        {/* 모드 선택 */}
        <div className="flex gap-2 bg-gray-900 rounded-xl p-1">
          <button
            onClick={() => setMode('multicam')}
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all ${
              mode === 'multicam'
                ? 'bg-violet-600 text-white shadow-lg'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            📱 멀티캠
          </button>
          <button
            onClick={() => setMode('timeline')}
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all ${
              mode === 'timeline'
                ? 'bg-emerald-600 text-white shadow-lg'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            🎞️ 타임라인캠
          </button>
        </div>

        {/* 모드 설명 */}
        <div className={`text-center text-xs px-4 py-2 rounded-lg ${
          mode === 'multicam'
            ? 'bg-violet-900/20 text-violet-300'
            : 'bg-emerald-900/20 text-emerald-300'
        }`}>
          {mode === 'multicam'
            ? '여러 기기로 동시에 촬영하고 AI가 교차편집합니다'
            : '자유롭게 촬영/중단하면 하나의 타임라인으로 자동 편집됩니다'
          }
        </div>

        {/* 새 촬영 + 참여 코드 */}
        <div className="bg-gray-900 rounded-2xl p-4 space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="촬영 제목 (선택)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="flex-1 min-w-0 bg-gray-800 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-500 outline-none focus:ring-2 focus:ring-purple-500"
            />
            <button
              onClick={createSession}
              disabled={loading}
              className={`px-4 py-2.5 rounded-xl text-sm font-semibold transition whitespace-nowrap ${
                mode === 'multicam'
                  ? 'bg-violet-600 hover:bg-violet-500 disabled:bg-gray-700'
                  : 'bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700'
              }`}
            >
              {loading ? '...' : '새 촬영'}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-gray-800" />
            <span className="text-gray-600 text-xs">또는 참여</span>
            <div className="flex-1 h-px bg-gray-800" />
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              placeholder="코드 2자리"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 2))}
              maxLength={2}
              className="flex-1 min-w-0 bg-gray-800 rounded-xl px-3 py-2.5 text-white text-center text-lg tracking-[0.2em] font-mono placeholder-gray-500 placeholder:text-sm placeholder:tracking-normal outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={joinSession}
              disabled={loading || joinCode.length < 2}
              className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 px-4 py-2.5 rounded-xl text-sm font-semibold transition whitespace-nowrap"
            >
              {loading ? '...' : '참여'}
            </button>
          </div>
        </div>

        {error && (
          <p className="text-red-400 text-center text-sm">{error}</p>
        )}

        {/* 사용법 + 버전 */}
        <div className="text-gray-600 text-xs text-center leading-relaxed space-y-1">
          <p>
            {mode === 'multicam'
              ? '세션 만들기 → 코드 공유 → 동시 촬영 → AI 교차편집'
              : '세션 만들기 → 코드 공유 → 자유 촬영 → AI 타임라인 편집'
            }
          </p>
          {version && (
            <p className="text-gray-700 font-mono">
              {version.front === version.server && version.front !== '0' ? (
                <span>#{version.front}</span>
              ) : (
                <span>front {version.front} · server {version.server}</span>
              )}
            </p>
          )}
        </div>

        {/* 최근 촬영 */}
        {recentSessions.length > 0 && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-400">최근 촬영</h2>
            <div className="space-y-1.5">
              {recentSessions.map((s) => {
                const doneResults = s.studio_results.filter(r => r.status === 'done');
                const clipCount = s.studio_clips.length;
                return (
                  <button
                    key={s.id}
                    onClick={() => router.push(`/studio/${s.id}/result`)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl bg-gray-900 hover:bg-gray-800 transition text-left"
                  >
                    <span className="text-base shrink-0">
                      {s.status === 'editing' ? '⏳' : doneResults.length > 0 ? '🎬' : '📹'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{s.title}</p>
                      <p className="text-xs text-gray-500">
                        {clipCount}클립
                        {doneResults.length > 0 && ` · ${doneResults.length}편집`}
                        {s.status === 'editing' && ' · 편집 중'}
                        {' · '}{formatRelativeTime(s.created_at)}
                      </p>
                    </div>
                    <span className="text-gray-600 text-xs shrink-0">→</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
