'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { useLang, LangToggle } from '@/lib/i18n';

type Mode = 'multicam' | 'timeline';

interface RecentSession {
  id: string;
  title: string;
  status: string;
  created_at: string;
  studio_results: { id: string; storage_path: string; duration_ms: number | null; status: string }[];
  studio_clips: { id: string }[];
}

function formatRelativeTime(dateStr: string, lang: 'ko' | 'en'): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return lang === 'ko' ? '방금 전' : 'just now';
  if (minutes < 60) return lang === 'ko' ? `${minutes}분 전` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return lang === 'ko' ? `${hours}시간 전` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return lang === 'ko' ? `${days}일 전` : `${days}d ago`;
}

export default function StudioPage() {
  const router = useRouter();
  const { user, signInWithGoogle } = useAuth();
  const { lang } = useLang();
  const [mode, setMode] = useState<Mode>('multicam');
  const [title, setTitle] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState<{ front: string; server: string } | null>(null);
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);

  const isSupaCam = typeof window !== 'undefined' && window.location.hostname.includes('supacam');

  const t = {
    title: lang === 'ko' ? 'SupaCam 슈파캠' : 'SupaCam',
    subtitle: lang === 'ko' ? '여러 카메라로 촬영 · AI 자동 편집' : 'Multi-camera recording · AI auto editing',
    multicam: lang === 'ko' ? '📱 멀티캠' : '📱 MultiCam',
    timeline: lang === 'ko' ? '🎞️ 타임라인캠' : '🎞️ Timeline',
    multicamDesc: lang === 'ko' ? '여러 기기로 동시에 촬영하고 AI가 교차편집합니다' : 'Record simultaneously from multiple devices with AI cross-editing',
    timelineDesc: lang === 'ko' ? '자유롭게 촬영/중단하면 하나의 타임라인으로 자동 편집됩니다' : 'Record and pause freely — auto-aligned on a single timeline',
    titlePlaceholder: lang === 'ko' ? '촬영 제목 (선택)' : 'Session title (optional)',
    newSession: lang === 'ko' ? '새 촬영' : 'New Session',
    orJoin: lang === 'ko' ? '또는 참여' : 'or join',
    codePlaceholder: lang === 'ko' ? '코드 2자리' : '2-digit code',
    join: lang === 'ko' ? '참여' : 'Join',
    multicamFlow: lang === 'ko' ? '세션 만들기 → 코드 공유 → 동시 촬영 → AI 교차편집' : 'Create → Share code → Record → AI cross-edit',
    timelineFlow: lang === 'ko' ? '세션 만들기 → 코드 공유 → 자유 촬영 → AI 타임라인 편집' : 'Create → Share code → Record → AI timeline edit',
    recentSessions: lang === 'ko' ? '최근 촬영' : 'Recent Sessions',
    clips: lang === 'ko' ? '클립' : 'clips',
    edits: lang === 'ko' ? '편집' : 'edits',
    editing: lang === 'ko' ? '편집 중' : 'editing',
    signIn: lang === 'ko' ? '로그인' : 'Sign In',
    projects: lang === 'ko' ? '프로젝트' : 'Projects',
    createFailed: lang === 'ko' ? '세션 생성 실패' : 'Failed to create session',
    notFound: lang === 'ko' ? '세션을 찾을 수 없습니다' : 'Session not found',
    defaultMulticam: lang === 'ko' ? '멀티캠 촬영' : 'MultiCam Session',
    defaultTimeline: lang === 'ko' ? '타임라인 촬영' : 'Timeline Session',
  };

  useEffect(() => {
    fetch('/api/studio/version').then(r => r.json()).then(setVersion).catch(() => {});
  }, []);

  // 사용자 로그인 상태 변경 시 최근 세션 갱신
  useEffect(() => {
    if (!user) {
      setRecentSessions([]);
      return;
    }
    const sb = (async () => {
      const { getBrowserSupabase } = await import('@/lib/auth');
      const supabase = getBrowserSupabase();
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        fetch('/api/studio/sessions/recent', {
          headers: { 'Authorization': `Bearer ${session.access_token}` },
        }).then(r => r.json()).then(setRecentSessions).catch(() => {});
      }
    })();
  }, [user]);

  const createSession = async () => {
    setLoading(true);
    setError('');
    try {
      const defaultTitle = mode === 'multicam' ? t.defaultMulticam : t.defaultTimeline;
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };

      // 로그인 상태면 auth 토큰 추가 (created_by 저장용)
      const { getBrowserSupabase } = await import('@/lib/auth');
      const supabase = getBrowserSupabase();
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      }

      const res = await fetch('/api/studio/sessions', {
        method: 'POST',
        headers,
        body: JSON.stringify({ title: title || defaultTitle }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      router.push(`/studio/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.createFailed);
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
      setError(err instanceof Error ? err.message : t.notFound);
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
      {/* 좌측 상단: 홈으로 가기 */}
      <div className="fixed top-4 left-4 z-50">
        <button
          onClick={() => router.push('/supacam-home')}
          className="bg-gray-900 hover:bg-gray-800 border border-gray-700 px-3 py-2 rounded-xl text-sm transition cursor-pointer text-gray-300"
        >
          ← {lang === 'ko' ? '홈' : 'Home'}
        </button>
      </div>

      {/* 우측 상단 버튼 */}
      <div className="fixed top-4 right-4 z-50 flex items-center gap-2">
        <LangToggle />
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
            <span className="text-gray-300">{user ? t.projects : t.signIn}</span>
          </button>
        )}
      </div>

      <div className="max-w-sm w-full space-y-4">
        {/* 타이틀 */}
        <div className="text-center pb-2">
          <h1 className="text-2xl font-bold">{t.title}</h1>
          <p className="text-gray-500 text-xs mt-1">{t.subtitle}</p>
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
            {t.multicam}
          </button>
          <button
            onClick={() => setMode('timeline')}
            className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all ${
              mode === 'timeline'
                ? 'bg-emerald-600 text-white shadow-lg'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {t.timeline}
          </button>
        </div>

        {/* 모드 설명 */}
        <div className={`text-center text-xs px-4 py-2 rounded-lg ${
          mode === 'multicam'
            ? 'bg-violet-900/20 text-violet-300'
            : 'bg-emerald-900/20 text-emerald-300'
        }`}>
          {mode === 'multicam' ? t.multicamDesc : t.timelineDesc}
        </div>

        {/* 새 촬영 + 참여 코드 */}
        <div className="bg-gray-900 rounded-2xl p-4 space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder={t.titlePlaceholder}
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
              {loading ? '...' : t.newSession}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-gray-800" />
            <span className="text-gray-600 text-xs">{t.orJoin}</span>
            <div className="flex-1 h-px bg-gray-800" />
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              placeholder={t.codePlaceholder}
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
              {loading ? '...' : t.join}
            </button>
          </div>
        </div>

        {error && (
          <p className="text-red-400 text-center text-sm">{error}</p>
        )}

        {/* 사용법 + 버전 */}
        <div className="text-gray-600 text-xs text-center leading-relaxed space-y-1">
          <p>
            {mode === 'multicam' ? t.multicamFlow : t.timelineFlow}
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
            <h2 className="text-sm font-semibold text-gray-400">{t.recentSessions}</h2>
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
                        {clipCount}{t.clips}
                        {doneResults.length > 0 && ` · ${doneResults.length}${t.edits}`}
                        {s.status === 'editing' && ` · ${t.editing}`}
                        {' · '}{formatRelativeTime(s.created_at, lang)}
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
