'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth, getBrowserSupabase } from '@/lib/auth';

interface ProjectItem {
  id: string;
  code: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
  project_clips: { id: string }[];
  project_members: { id: string; name: string; role: string }[];
  project_results: { id: string; status: string; duration_ms: number | null; created_at: string }[];
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return '방금 전';
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}일 전`;
  return `${Math.floor(days / 30)}개월 전`;
}

export default function ProjectsPage() {
  const { user, loading: authLoading, signOut } = useAuth();
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  const getToken = useCallback(async () => {
    const sb = getBrowserSupabase();
    const { data: { session } } = await sb.auth.getSession();
    return session?.access_token || '';
  }, []);

  const loadProjects = useCallback(async () => {
    try {
      const token = await getToken();
      if (!token) {
        setLoading(false);
        return;
      }
      const res = await fetch('/api/projects', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setProjects(await res.json());
    } catch {
      // 네트워크 에러 등
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace('/login');
      return;
    }
    if (user) loadProjects();
  }, [user, authLoading, router, loadProjects]);

  const createProject = async () => {
    // 무료 유저: 프로젝트 1개 제한
    if (user?.plan === 'free' && projects.length >= 1) {
      setError('무료 요금제에서는 프로젝트를 1개만 만들 수 있어요. Plus로 업그레이드하세요!');
      return;
    }
    setCreating(true);
    setError('');
    try {
      const token = await getToken();
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ title: title || '새 프로젝트' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      router.push(`/projects/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '생성 실패');
    } finally {
      setCreating(false);
    }
  };

  const joinProject = async () => {
    if (!joinCode.trim()) return;
    setCreating(true);
    setError('');
    try {
      // 코드로 프로젝트 찾기
      const token = await getToken();
      const res = await fetch(`/api/projects?code=${joinCode.trim().toUpperCase()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();

      // 배열에서 코드 매칭 찾기
      const found = Array.isArray(data) ? data.find((p: ProjectItem) => p.code === joinCode.trim().toUpperCase()) : null;
      if (!found) {
        // 서비스 키로 코드 검색
        const searchRes = await fetch(`/api/projects/${joinCode.trim().toUpperCase()}/join-by-code`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ userId: user?.id, name: user?.name }),
        });
        if (searchRes.ok) {
          const joinData = await searchRes.json();
          router.push(`/projects/${joinData.projectId}`);
          return;
        }
        throw new Error('프로젝트를 찾을 수 없습니다');
      }

      // 멤버로 참여
      await fetch(`/api/projects/${found.id}/join`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: user?.id, name: user?.name }),
      });
      router.push(`/projects/${found.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '참여 실패');
    } finally {
      setCreating(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return null; // useEffect에서 /login으로 리다이렉트 중
  }

  return (
    <div className="min-h-screen bg-black text-white">
      {/* 헤더 */}
      <div className="px-4 py-3 bg-gray-900 border-b border-gray-800">
        <div className="max-w-lg mx-auto flex items-center justify-between">
          <h1 className="text-lg font-bold">내 프로젝트</h1>
          <div className="flex items-center gap-3">
            {user && (
              <span className="text-xs text-gray-400">{user.name}</span>
            )}
            <button onClick={signOut} className="text-xs text-gray-500 hover:text-gray-300">
              로그아웃
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-lg mx-auto p-4 space-y-4">
        {/* 새 프로젝트 + 참여 */}
        <div className="bg-gray-900 rounded-2xl p-4 space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="프로젝트 이름 (선택)"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="flex-1 min-w-0 bg-gray-800 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-500 outline-none focus:ring-2 focus:ring-purple-500"
            />
            <button
              onClick={createProject}
              disabled={creating}
              className="bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 px-4 py-2.5 rounded-xl text-sm font-semibold transition whitespace-nowrap"
            >
              {creating ? '...' : '새 프로젝트'}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-gray-800" />
            <span className="text-gray-600 text-xs">또는 코드로 참여</span>
            <div className="flex-1 h-px bg-gray-800" />
          </div>

          <div className="flex gap-2">
            <input
              type="text"
              placeholder="프로젝트 코드 6자리"
              value={joinCode}
              onChange={(e) => setJoinCode(e.target.value.toUpperCase().slice(0, 6))}
              maxLength={6}
              className="flex-1 min-w-0 bg-gray-800 rounded-xl px-3 py-2.5 text-white text-center text-lg tracking-[0.15em] font-mono placeholder-gray-500 placeholder:text-sm placeholder:tracking-normal outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={joinProject}
              disabled={creating || joinCode.length < 6}
              className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 px-4 py-2.5 rounded-xl text-sm font-semibold transition whitespace-nowrap"
            >
              참여
            </button>
          </div>
        </div>

        {error && <p className="text-red-400 text-center text-sm">{error}</p>}

        {/* 프로젝트 목록 */}
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin" />
          </div>
        ) : projects.length > 0 ? (
          <div className="space-y-2">
            {projects.map((p) => {
              const clipCount = p.project_clips.length;
              const memberCount = p.project_members.length;
              const doneResults = p.project_results.filter(r => r.status === 'done');
              return (
                <button
                  key={p.id}
                  onClick={() => router.push(`/projects/${p.id}`)}
                  className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-gray-900 hover:bg-gray-800 transition text-left"
                >
                  <span className="text-xl shrink-0">
                    {p.status === 'editing' ? '⏳' : doneResults.length > 0 ? '🎬' : '📁'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{p.title}</p>
                    <p className="text-xs text-gray-500">
                      {memberCount}명 · {clipCount}클립
                      {doneResults.length > 0 && ` · ${doneResults.length}편집`}
                      {' · '}{formatRelativeTime(p.updated_at)}
                    </p>
                  </div>
                  <span className="text-gray-600 text-xs font-mono shrink-0">{p.code}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <p className="text-lg mb-1">아직 프로젝트가 없어요</p>
            <p className="text-sm">새 프로젝트를 만들거나 코드로 참여하세요</p>
          </div>
        )}

        {/* 기존 스튜디오 링크 */}
        <button
          onClick={() => router.push('/studio')}
          className="w-full text-gray-600 hover:text-gray-400 text-xs text-center py-2 transition"
        >
          기존 멀티캠 스튜디오 (1회성) →
        </button>
      </div>
    </div>
  );
}
