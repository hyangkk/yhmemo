'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function StudioPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState<{ front: string; server: string } | null>(null);

  useEffect(() => {
    fetch('/api/studio/version').then(r => r.json()).then(setVersion).catch(() => {});
  }, []);

  const createSession = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/studio/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title || '새 촬영' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      router.push(`/${data.id}`);
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
      router.push(`/${data.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '세션을 찾을 수 없습니다');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-4">
      <div className="max-w-sm w-full space-y-4">
        {/* 타이틀 */}
        <div className="text-center pb-2">
          <h1 className="text-2xl font-bold">멀티캠 스튜디오</h1>
          <p className="text-gray-500 text-xs mt-1">여러 카메라로 동시 촬영 · 자동 편집</p>
        </div>

        {/* 새 촬영 + 참여 코드 통합 */}
        <div className="bg-gray-900 rounded-2xl p-4 space-y-3">
          {/* 새 촬영 */}
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
              className="bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 px-4 py-2.5 rounded-xl text-sm font-semibold transition whitespace-nowrap"
            >
              {loading ? '...' : '새 촬영'}
            </button>
          </div>

          {/* 구분선 */}
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-gray-800" />
            <span className="text-gray-600 text-xs">또는 참여</span>
            <div className="flex-1 h-px bg-gray-800" />
          </div>

          {/* 코드로 참여 */}
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
          <p>세션 만들기 → 코드 공유 → 각 폰에서 참여 → 동시 촬영 → 자동 편집</p>
          {version && (
            <p className="text-gray-700 font-mono">
              {version.front === version.server && version.front !== '0' ? (
                <span>#{version.front}</span>
              ) : (
                <span>
                  front {version.front} · server {version.server}
                </span>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
