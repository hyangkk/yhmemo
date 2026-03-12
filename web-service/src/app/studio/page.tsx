'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function StudioPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  return (
    <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-6">
      <div className="max-w-md w-full space-y-8">
        {/* 로고/타이틀 */}
        <div className="text-center">
          <div className="text-5xl mb-3">🎬</div>
          <h1 className="text-3xl font-bold">멀티캠 스튜디오</h1>
          <p className="text-gray-400 mt-2">
            여러 대의 카메라로 동시 촬영하고<br />
            자동으로 편집된 영상을 받아보세요
          </p>
        </div>

        {/* 새 촬영 세션 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-4">
          <h2 className="text-lg font-semibold">새 촬영 시작</h2>
          <input
            type="text"
            placeholder="촬영 제목 (선택)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full bg-gray-800 rounded-xl px-4 py-3 text-white placeholder-gray-500 outline-none focus:ring-2 focus:ring-purple-500"
          />
          <button
            onClick={createSession}
            disabled={loading}
            className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 text-white font-semibold py-3 rounded-xl transition"
          >
            {loading ? '생성 중...' : '촬영 세션 만들기'}
          </button>
        </div>

        {/* 구분선 */}
        <div className="flex items-center gap-4">
          <div className="flex-1 h-px bg-gray-800" />
          <span className="text-gray-500 text-sm">또는</span>
          <div className="flex-1 h-px bg-gray-800" />
        </div>

        {/* 코드로 참여 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-4">
          <h2 className="text-lg font-semibold">코드로 참여</h2>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            placeholder="참여 코드 (2자리)"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value.replace(/\D/g, '').slice(0, 2))}
            maxLength={2}
            className="w-full bg-gray-800 rounded-xl px-4 py-3 text-white text-center text-4xl tracking-[0.5em] font-mono placeholder-gray-500 placeholder:text-base placeholder:tracking-normal outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={joinSession}
            disabled={loading || joinCode.length < 2}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white font-semibold py-3 rounded-xl transition"
          >
            {loading ? '참여 중...' : '세션 참여하기'}
          </button>
        </div>

        {error && (
          <p className="text-red-400 text-center text-sm">{error}</p>
        )}

        {/* 사용법 */}
        <div className="text-center text-gray-500 text-sm space-y-1">
          <p>1. 촬영 세션을 만들고 참여 코드를 공유하세요</p>
          <p>2. 각 폰에서 코드를 입력해 카메라로 참여하세요</p>
          <p>3. 호스트가 녹화를 시작하면 모든 카메라가 동시에 촬영!</p>
          <p>4. 촬영 종료 후 자동으로 편집된 영상을 받아보세요</p>
        </div>
      </div>
    </div>
  );
}
