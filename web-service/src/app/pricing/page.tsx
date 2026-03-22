'use client';

import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';

export default function PricingPage() {
  const { user, signInWithGoogle } = useAuth();
  const router = useRouter();

  const handleSelectPlan = (plan: string) => {
    if (!user) {
      signInWithGoogle();
      return;
    }
    if (plan === 'free') {
      router.push('/projects');
      return;
    }
    // Plus 결제 → Paddle checkout
    router.push('/projects?upgrade=plus');
  };

  return (
    <div className="min-h-screen bg-black text-white">
      {/* 헤더 */}
      <div className="px-4 py-3 bg-gray-900 border-b border-gray-800">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <button onClick={() => router.push('/')} className="text-gray-400 hover:text-white text-sm">← 홈</button>
          {user ? (
            <button onClick={() => router.push('/projects')} className="text-sm text-purple-400 hover:text-purple-300">내 프로젝트</button>
          ) : (
            <button onClick={signInWithGoogle} className="text-sm text-purple-400 hover:text-purple-300">로그인</button>
          )}
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-4 py-12">
        <div className="text-center mb-10">
          <h1 className="text-3xl font-bold mb-3">요금제</h1>
          <p className="text-gray-400">멀티캠 촬영과 AI 자동 편집을 시작하세요</p>
        </div>

        <div className="grid md:grid-cols-2 gap-4 max-w-2xl mx-auto">
          {/* Free */}
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 space-y-4">
            <div>
              <h2 className="text-xl font-bold">{PLANS.free.name}</h2>
              <div className="mt-2">
                <span className="text-3xl font-bold">$0</span>
                <span className="text-gray-500 ml-1">/월</span>
              </div>
              <p className="text-gray-400 text-sm mt-1">{PLANS.free.description}</p>
            </div>
            <ul className="space-y-2">
              {PLANS.free.features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-gray-500">✓</span> {f}
                </li>
              ))}
            </ul>
            <button
              onClick={() => handleSelectPlan('free')}
              className="w-full bg-gray-700 hover:bg-gray-600 py-2.5 rounded-xl text-sm font-semibold transition"
            >
              무료로 시작
            </button>
          </div>

          {/* Plus */}
          <div className="bg-purple-900/20 border-2 border-purple-500/50 rounded-2xl p-6 space-y-4 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-purple-600 text-xs font-bold px-3 py-1 rounded-full">
              추천
            </div>
            <div>
              <h2 className="text-xl font-bold">{PLANS.plus.name}</h2>
              <div className="mt-2">
                <span className="text-3xl font-bold">${PLANS.plus.price}</span>
                <span className="text-gray-400 ml-1">/월</span>
              </div>
              <p className="text-gray-400 text-sm mt-1">{PLANS.plus.description}</p>
            </div>
            <ul className="space-y-2">
              {PLANS.plus.features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-purple-400">✓</span> {f}
                </li>
              ))}
            </ul>
            <button
              onClick={() => handleSelectPlan('plus')}
              className="w-full bg-purple-600 hover:bg-purple-500 py-2.5 rounded-xl text-sm font-bold transition"
            >
              Plus 시작하기
            </button>
          </div>
        </div>

        {/* 하단 링크 */}
        <div className="text-center mt-10 space-x-4 text-xs text-gray-600">
          <a href="/legal/terms" className="hover:text-gray-400">이용약관</a>
          <span className="text-gray-700">·</span>
          <span className="text-gray-600">Payments by <a href="https://paddle.com" target="_blank" rel="noopener noreferrer" className="hover:text-gray-400">Paddle</a></span>
        </div>
      </div>
    </div>
  );
}
