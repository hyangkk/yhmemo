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
    heroTitle1: '여러 카메라, 하나의 영상',
    heroTitle2: 'AI가 자동으로 편집',
    heroDesc: '멀티캠으로 동시 촬영하거나, 타임라인캠으로 자유롭게 촬영하세요. AI가 최적의 장면을 골라 완성된 영상을 만들어줍니다.',
    cta: '무료로 시작하기',
    multicamTitle: '멀티캠',
    multicamBadge: '동시 촬영',
    multicamDesc: '여러 대의 카메라로 같은 순간을 동시에 촬영합니다. AI가 베스트 앵글을 자동 선택하고 교차 편집합니다.',
    multicamFeatures: ['실시간 동기화 촬영', '2자리 코드로 간편 참여', 'AI 자동 교차편집'],
    timelineTitle: '타임라인캠',
    timelineBadge: '연속 촬영',
    timelineDesc: '여러 카메라로 자유롭게 촬영하고 멈추세요. 모든 영상이 하나의 타임라인에 자동 정렬되어 편집됩니다.',
    timelineFeatures: ['촬영/중단 자유롭게', '멀티 디바이스 타임라인', '자동 정렬 & 편집'],
    howTitle: '이렇게 사용하세요',
    howSteps: [
      { num: '1', title: '촬영 모드 선택', desc: '멀티캠 또는 타임라인캠을 선택하세요' },
      { num: '2', title: '코드 공유 & 촬영', desc: '참여 코드를 공유하고 각 기기에서 촬영하세요' },
      { num: '3', title: 'AI 자동 편집', desc: 'AI가 최적의 장면을 골라 완성 영상을 만듭니다' },
    ],
    pricingTitle: '요금제',
    pricingDesc: '각 모드 2회씩 무료. 더 많이 촬영하려면 Plus로 업그레이드하세요.',
    perMonth: '/월',
    recommended: '추천',
    startFree: '무료로 시작',
    startPlus: 'Plus 시작하기',
    footer: 'AI-powered multi-camera editing.',
  },
  en: {
    openStudio: 'Open Studio',
    getStarted: 'Get Started',
    badge: 'AI-Powered Video Editing',
    heroTitle1: 'Multiple cameras, one video',
    heroTitle2: 'Edited by AI automatically',
    heroDesc: 'Shoot simultaneously with MultiCam, or record freely with Timeline Cam. AI picks the best shots and creates a polished final video.',
    cta: 'Start for Free',
    multicamTitle: 'MultiCam',
    multicamBadge: 'Simultaneous',
    multicamDesc: 'Record the same moment from multiple cameras simultaneously. AI auto-selects the best angles and creates cross-cuts.',
    multicamFeatures: ['Real-time synced recording', 'Join with 2-digit code', 'AI auto cross-editing'],
    timelineTitle: 'Timeline Cam',
    timelineBadge: 'Continuous',
    timelineDesc: 'Record and pause freely from multiple cameras. All footage auto-aligns on a single timeline for seamless editing.',
    timelineFeatures: ['Start/stop anytime', 'Multi-device timeline', 'Auto-align & edit'],
    howTitle: 'How it works',
    howSteps: [
      { num: '1', title: 'Choose a mode', desc: 'Select MultiCam or Timeline Cam' },
      { num: '2', title: 'Share code & record', desc: 'Share the join code and start recording' },
      { num: '3', title: 'AI auto-edit', desc: 'AI picks the best shots and creates the final video' },
    ],
    pricingTitle: 'Pricing',
    pricingDesc: '2 free sessions per mode. Upgrade to Plus for unlimited.',
    perMonth: '/mo',
    recommended: 'Best Value',
    startFree: 'Start Free',
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

  const ActionButton = ({ className, children }: { className?: string; children: React.ReactNode }) => {
    if (user) {
      return <Link href="/studio" className={className}>{children}</Link>;
    }
    return <button onClick={signInWithGoogle} className={className}>{children}</button>;
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-950 via-gray-900 to-gray-950 text-white">
      {/* Nav */}
      <nav className="max-w-5xl mx-auto px-4 py-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🎬</span>
          <span className="text-xl font-bold bg-gradient-to-r from-violet-400 to-purple-500 bg-clip-text text-transparent">
            SupaCam
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
            className="text-xs text-gray-400 hover:text-white border border-gray-700 rounded-md px-2 py-1 transition-colors"
          >
            {lang === 'ko' ? 'EN' : '한국어'}
          </button>
          <Link href="/pricing" className="text-sm text-gray-400 hover:text-white transition-colors">
            {l.pricingTitle}
          </Link>
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

        <div className="mt-10">
          <ActionButton className="inline-block px-8 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 text-lg font-semibold transition-colors shadow-lg shadow-violet-600/25">
            {l.cta}
          </ActionButton>
        </div>
      </section>

      {/* Two Modes */}
      <section className="max-w-5xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* MultiCam */}
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-8 hover:border-violet-700/50 transition-colors group">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-4xl">📱</span>
              <div>
                <h3 className="text-xl font-bold">{l.multicamTitle}</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/50 text-blue-300 font-medium">
                  {l.multicamBadge}
                </span>
              </div>
            </div>
            <p className="text-sm text-gray-400 mb-5 leading-relaxed">{l.multicamDesc}</p>
            <ul className="space-y-2">
              {l.multicamFeatures.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-violet-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
          </div>

          {/* Timeline Cam */}
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-8 hover:border-violet-700/50 transition-colors group">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-4xl">🎞️</span>
              <div>
                <h3 className="text-xl font-bold">{l.timelineTitle}</h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-900/50 text-emerald-300 font-medium">
                  {l.timelineBadge}
                </span>
              </div>
            </div>
            <p className="text-sm text-gray-400 mb-5 leading-relaxed">{l.timelineDesc}</p>
            <ul className="space-y-2">
              {l.timelineFeatures.map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-emerald-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-4xl mx-auto px-4 pb-20">
        <h2 className="text-2xl font-bold text-center mb-10">{l.howTitle}</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {l.howSteps.map((step) => (
            <div key={step.num} className="text-center">
              <div className="w-12 h-12 rounded-full bg-violet-600/20 text-violet-400 text-xl font-bold flex items-center justify-center mx-auto mb-4">
                {step.num}
              </div>
              <h3 className="font-semibold mb-2">{step.title}</h3>
              <p className="text-sm text-gray-400">{step.desc}</p>
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
                  <span className="text-green-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <ActionButton className="block w-full text-center px-4 py-2.5 rounded-lg border border-gray-700 hover:border-gray-600 text-sm font-medium transition-colors">
                {l.startFree}
              </ActionButton>
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
                  <span className="text-violet-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <ActionButton className="block w-full text-center px-4 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-bold transition-colors">
                {l.startPlus}
              </ActionButton>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8">
        <div className="max-w-4xl mx-auto px-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-gray-500">&copy; 2026 SupaCam. {l.footer}</p>
            <div className="flex items-center gap-4 text-sm">
              <Link href="/pricing" className="text-gray-500 hover:text-gray-300 transition-colors">Pricing</Link>
              <Link href="/legal/terms" className="text-gray-500 hover:text-gray-300 transition-colors">Terms</Link>
              <Link href="/privacy" className="text-gray-500 hover:text-gray-300 transition-colors">Privacy</Link>
              <Link href="/refund" className="text-gray-500 hover:text-gray-300 transition-colors">Refund</Link>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}
