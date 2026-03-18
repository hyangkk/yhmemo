'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth, getBrowserSupabase } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';

export default function MyPage() {
  const { user, loading: authLoading, signOut, refreshProfile } = useAuth();
  const router = useRouter();
  const [subscribing, setSubscribing] = useState(false);
  const [plan, setPlan] = useState<string>('free');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace('/login');
      return;
    }
    setPlan(user.plan || 'free');
  }, [user, authLoading, router]);

  const getToken = useCallback(async () => {
    const sb = getBrowserSupabase();
    const { data: { session } } = await sb.auth.getSession();
    return session?.access_token || '';
  }, []);

  const handleSubscribe = async () => {
    setSubscribing(true);
    setMessage('');
    try {
      const token = await getToken();
      const res = await fetch('/api/subscribe', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('구독 실패');
      await refreshProfile();
      setPlan('plus');
      setMessage('Plus 구독이 활성화되었습니다!');
    } catch {
      setMessage('구독 처리 중 오류가 발생했습니다.');
    } finally {
      setSubscribing(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return null;

  const isPlus = plan === 'plus';

  return (
    <div className="min-h-screen bg-black text-white">
      {/* 헤더 */}
      <div className="px-4 py-3 bg-gray-900 border-b border-gray-800">
        <div className="max-w-lg mx-auto flex items-center justify-between">
          <button
            onClick={() => router.back()}
            className="text-gray-400 hover:text-white text-sm cursor-pointer"
          >
            ← 뒤로
          </button>
          <h1 className="text-lg font-bold">마이페이지</h1>
          <div className="w-12" />
        </div>
      </div>

      <div className="max-w-lg mx-auto p-4 space-y-6">
        {/* 프로필 카드 */}
        <div className="bg-gray-900 rounded-2xl p-6">
          <div className="flex items-center gap-4">
            {user.avatar_url ? (
              <img src={user.avatar_url} alt="" className="w-16 h-16 rounded-full" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-purple-600 flex items-center justify-center text-2xl font-bold">
                {user.name?.charAt(0) || 'U'}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-lg font-bold truncate">{user.name}</p>
              <p className="text-sm text-gray-400 truncate">{user.email}</p>
              <div className="mt-1">
                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${
                  isPlus
                    ? 'bg-purple-600/30 text-purple-300 border border-purple-500/50'
                    : 'bg-gray-700 text-gray-400'
                }`}>
                  {isPlus ? 'Plus' : 'Free'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 구독 관리 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-4">
          <h2 className="text-base font-bold">구독 관리</h2>

          {isPlus ? (
            <div className="space-y-3">
              <div className="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-purple-300">Plus 구독 중</p>
                    <p className="text-sm text-gray-400 mt-1">${PLANS.plus.price}/월 · 테스트 기간</p>
                  </div>
                  <span className="text-purple-400 text-2xl">✓</span>
                </div>
              </div>
              <ul className="space-y-1.5">
                {PLANS.plus.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                    <span className="text-purple-400">✓</span> {f}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-gray-800 rounded-xl p-4">
                <p className="text-sm text-gray-400">현재 무료 요금제를 사용 중입니다.</p>
                <p className="text-sm text-gray-500 mt-1">Plus로 업그레이드하면 모든 기능을 사용할 수 있어요.</p>
              </div>

              {/* Plus 요금제 카드 */}
              <div className="border border-purple-500/50 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-bold text-lg">Plus</p>
                    <p className="text-gray-400 text-sm">{PLANS.plus.description}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold">${PLANS.plus.price}</p>
                    <p className="text-xs text-gray-500">/월</p>
                  </div>
                </div>
                <ul className="space-y-1.5">
                  {PLANS.plus.features.map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                      <span className="text-purple-400">✓</span> {f}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={handleSubscribe}
                  disabled={subscribing}
                  className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 py-3 rounded-xl text-sm font-bold transition cursor-pointer"
                >
                  {subscribing ? '처리 중...' : 'Plus 구독하기 — $9/월'}
                </button>
                <p className="text-xs text-gray-600 text-center">테스트 기간 — 실제 결제 없이 즉시 활성화</p>
              </div>
            </div>
          )}

          {message && (
            <p className={`text-center text-sm ${message.includes('활성화') ? 'text-green-400' : 'text-red-400'}`}>
              {message}
            </p>
          )}
        </div>

        {/* 계정 관리 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-3">
          <h2 className="text-base font-bold">계정</h2>
          <button
            onClick={() => router.push('/projects')}
            className="w-full text-left px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm transition cursor-pointer"
          >
            내 프로젝트 →
          </button>
          <button
            onClick={signOut}
            className="w-full text-left px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-red-400 transition cursor-pointer"
          >
            로그아웃
          </button>
        </div>
      </div>
    </div>
  );
}
