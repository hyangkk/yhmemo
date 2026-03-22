'use client';

import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';

export default function SupaCamHome() {
  const { user, signInWithGoogle } = useAuth();

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-950 to-gray-900 text-white">
      {/* Nav */}
      <nav className="max-w-5xl mx-auto px-4 py-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🎬</span>
          <span className="text-xl font-bold bg-gradient-to-r from-violet-400 to-purple-500 bg-clip-text text-transparent">
            SupaCam
          </span>
        </div>
        <div className="flex items-center gap-4">
          {user ? (
            <Link
              href="/studio"
              className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors"
            >
              스튜디오 열기
            </Link>
          ) : (
            <button
              onClick={signInWithGoogle}
              className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors"
            >
              시작하기
            </button>
          )}
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-4 pt-16 pb-20 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-900/40 text-violet-300 text-sm font-medium mb-6">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          AI 기반 영상 편집
        </div>

        <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight leading-tight">
          다중 카메라 영상을
          <br />
          <span className="bg-gradient-to-r from-violet-400 to-purple-500 bg-clip-text text-transparent">
            AI가 자동으로 편집
          </span>
        </h1>

        <p className="mt-6 text-lg text-gray-400 max-w-2xl mx-auto">
          여러 대의 카메라로 촬영한 영상을 업로드하면, AI가 최적의 장면을 골라
          교차 편집하고 완성된 영상을 만들어줍니다.
        </p>

        <div className="mt-10 flex items-center justify-center gap-4">
          {user ? (
            <Link
              href="/studio"
              className="px-8 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-lg font-semibold transition-colors shadow-lg shadow-violet-600/25"
            >
              무료로 시작하기
            </Link>
          ) : (
            <button
              onClick={signInWithGoogle}
              className="px-8 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-lg font-semibold transition-colors shadow-lg shadow-violet-600/25"
            >
              무료로 시작하기
            </button>
          )}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            {
              icon: '📱',
              title: '다중 카메라 동기화',
              desc: '여러 기기에서 동시 촬영. 타임코드 자동 동기화로 완벽한 멀티캠 촬영.',
            },
            {
              icon: '🤖',
              title: 'AI 자동 교차편집',
              desc: 'AI가 각 카메라의 베스트 장면을 분석하고 자연스러운 교차편집을 생성.',
            },
            {
              icon: '🎞️',
              title: '즉시 결과물',
              desc: '편집 완료 후 바로 다운로드. 자막, BGM, 효과까지 자동 적용.',
            },
          ].map((f) => (
            <div
              key={f.title}
              className="rounded-2xl border border-gray-800 bg-gray-900/50 p-6 hover:border-violet-700 transition-colors"
            >
              <div className="text-3xl mb-4">{f.icon}</div>
              <h3 className="text-lg font-bold mb-2">{f.title}</h3>
              <p className="text-sm text-gray-400">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="max-w-4xl mx-auto px-4 pb-24">
        <h2 className="text-3xl font-bold text-center mb-4">요금제</h2>
        <p className="text-center text-gray-400 mb-12">
          무료로 시작하고, 필요할 때 업그레이드하세요.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
          {/* Free */}
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-8">
            <h3 className="text-xl font-bold">{PLANS.free.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold">$0</span>
              <span className="text-gray-400">/월</span>
            </div>
            <p className="mt-2 text-sm text-gray-400">{PLANS.free.description}</p>
            <ul className="mt-6 space-y-3">
              {PLANS.free.features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-green-400">✓</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              {user ? (
                <Link
                  href="/studio"
                  className="block w-full text-center px-4 py-2.5 rounded-lg border border-gray-700 hover:border-gray-600 text-sm font-medium transition-colors"
                >
                  시작하기
                </Link>
              ) : (
                <button
                  onClick={signInWithGoogle}
                  className="w-full px-4 py-2.5 rounded-lg border border-gray-700 hover:border-gray-600 text-sm font-medium transition-colors"
                >
                  시작하기
                </button>
              )}
            </div>
          </div>

          {/* Plus */}
          <div className="rounded-2xl border-2 border-violet-600 bg-gray-900/50 p-8 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-violet-600 text-xs font-bold">
              추천
            </div>
            <h3 className="text-xl font-bold">{PLANS.plus.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold">${PLANS.plus.price}</span>
              <span className="text-gray-400">/월</span>
            </div>
            <p className="mt-2 text-sm text-gray-400">{PLANS.plus.description}</p>
            <ul className="mt-6 space-y-3">
              {PLANS.plus.features.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-violet-400">✓</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <Link
                href="/studio?upgrade=plus"
                className="block w-full text-center px-4 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-bold transition-colors"
              >
                Plus 시작하기
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8 text-center text-sm text-gray-500">
        <p>&copy; 2026 SupaCam. AI-powered multi-camera editing.</p>
      </footer>
    </main>
  );
}
