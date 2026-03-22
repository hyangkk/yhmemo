'use client';

import Link from 'next/link';
import { useState, useEffect } from 'react';
import { useAuth } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';

type Lang = 'ko' | 'en';

const t = {
  ko: {
    openStudio: '스튜디오 열기',
    getStarted: '시작하기',
    badge: 'AI 기반 영상 편집',
    heroTitle1: '다중 카메라 영상을',
    heroTitle2: 'AI가 자동으로 편집',
    heroDesc: '여러 대의 카메라로 촬영한 영상을 업로드하면, AI가 최적의 장면을 골라 교차 편집하고 완성된 영상을 만들어줍니다.',
    cta: '무료로 시작하기',
    features: [
      { icon: '📱', title: '다중 카메라 동기화', desc: '여러 기기에서 동시 촬영. 타임코드 자동 동기화로 완벽한 멀티캠 촬영.' },
      { icon: '🤖', title: 'AI 자동 교차편집', desc: 'AI가 각 카메라의 베스트 장면을 분석하고 자연스러운 교차편집을 생성.' },
      { icon: '🎞️', title: '즉시 결과물', desc: '편집 완료 후 바로 다운로드. 자막, BGM, 효과까지 자동 적용.' },
    ],
    pricingTitle: '요금제',
    pricingDesc: '무료로 시작하고, 필요할 때 업그레이드하세요.',
    perMonth: '/월',
    recommended: '추천',
    startFree: '시작하기',
    startPlus: 'Plus 시작하기',
    footer: 'AI-powered multi-camera editing.',
  },
  en: {
    openStudio: 'Open Studio',
    getStarted: 'Get Started',
    badge: 'AI-Powered Video Editing',
    heroTitle1: 'Multi-camera videos,',
    heroTitle2: 'edited by AI automatically',
    heroDesc: 'Upload footage from multiple cameras and let AI pick the best shots, create seamless cross-cuts, and deliver a polished final video.',
    cta: 'Start for Free',
    features: [
      { icon: '📱', title: 'Multi-Camera Sync', desc: 'Record simultaneously from multiple devices. Automatic timecode sync for perfect multicam shoots.' },
      { icon: '🤖', title: 'AI Auto Cross-Editing', desc: 'AI analyzes the best moments from each camera and generates natural cross-cuts.' },
      { icon: '🎞️', title: 'Instant Results', desc: 'Download right after editing. Subtitles, BGM, and effects applied automatically.' },
    ],
    pricingTitle: 'Pricing',
    pricingDesc: 'Start free, upgrade when you need more.',
    perMonth: '/mo',
    recommended: 'Best Value',
    startFree: 'Get Started',
    startPlus: 'Start Plus',
    footer: 'AI-powered multi-camera editing.',
  },
} as const;

export default function SupaCamHome() {
  const { user, signInWithGoogle } = useAuth();
  const [lang, setLang] = useState<Lang>('en');

  useEffect(() => {
    const browserLang = navigator.language || '';
    if (browserLang.startsWith('ko')) {
      setLang('ko');
    }
  }, []);

  const l = t[lang];

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
          <button
            onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
            className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-md px-2 py-1 transition-colors"
          >
            {lang === 'ko' ? 'EN' : '한국어'}
          </button>
          {user ? (
            <Link
              href="/studio"
              className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors"
            >
              {l.openStudio}
            </Link>
          ) : (
            <button
              onClick={signInWithGoogle}
              className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors"
            >
              {l.getStarted}
            </button>
          )}
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-4xl mx-auto px-4 pt-16 pb-20 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-900/40 text-violet-300 text-sm font-medium mb-6">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          {l.badge}
        </div>

        <h1 className="text-5xl sm:text-6xl font-extrabold tracking-tight leading-tight">
          {l.heroTitle1}
          <br />
          <span className="bg-gradient-to-r from-violet-400 to-purple-500 bg-clip-text text-transparent">
            {l.heroTitle2}
          </span>
        </h1>

        <p className="mt-6 text-lg text-gray-400 max-w-2xl mx-auto">
          {l.heroDesc}
        </p>

        <div className="mt-10 flex items-center justify-center gap-4">
          {user ? (
            <Link
              href="/studio"
              className="px-8 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-lg font-semibold transition-colors shadow-lg shadow-violet-600/25"
            >
              {l.cta}
            </Link>
          ) : (
            <button
              onClick={signInWithGoogle}
              className="px-8 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-lg font-semibold transition-colors shadow-lg shadow-violet-600/25"
            >
              {l.cta}
            </button>
          )}
        </div>
      </section>

      {/* Features */}
      <section className="max-w-5xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {l.features.map((f) => (
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
        <h2 className="text-3xl font-bold text-center mb-4">{l.pricingTitle}</h2>
        <p className="text-center text-gray-400 mb-12">{l.pricingDesc}</p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
          {/* Free */}
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-8">
            <h3 className="text-xl font-bold">{PLANS.free.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold">$0</span>
              <span className="text-gray-400">{l.perMonth}</span>
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
                  {l.startFree}
                </Link>
              ) : (
                <button
                  onClick={signInWithGoogle}
                  className="w-full px-4 py-2.5 rounded-lg border border-gray-700 hover:border-gray-600 text-sm font-medium transition-colors"
                >
                  {l.startFree}
                </button>
              )}
            </div>
          </div>

          {/* Plus */}
          <div className="rounded-2xl border-2 border-violet-600 bg-gray-900/50 p-8 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-violet-600 text-xs font-bold">
              {l.recommended}
            </div>
            <h3 className="text-xl font-bold">{PLANS.plus.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold">${PLANS.plus.price}</span>
              <span className="text-gray-400">{l.perMonth}</span>
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
                {l.startPlus}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8 text-center text-sm text-gray-500">
        <div className="max-w-4xl mx-auto px-4 flex items-center justify-center gap-4">
          <p>&copy; 2026 SupaCam. {l.footer}</p>
          <Link href="/legal/terms" className="text-gray-600 hover:text-gray-400">Terms</Link>
          <Link href="/pricing" className="text-gray-600 hover:text-gray-400">Pricing</Link>
        </div>
      </footer>
    </main>
  );
}
