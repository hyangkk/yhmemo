'use client';

import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';
import { useLang, LangToggle } from '@/lib/i18n';

export default function PricingPage() {
  const { user, signInWithGoogle } = useAuth();
  const { lang } = useLang();

  const ActionButton = ({ variant, children }: { variant: 'outline' | 'primary'; children: React.ReactNode }) => {
    const base = variant === 'primary'
      ? 'bg-violet-600 hover:bg-violet-500 text-sm font-bold'
      : 'border border-gray-700 hover:border-gray-600 text-sm font-medium';

    if (user) {
      return <Link href="/studio" className={`block w-full text-center px-4 py-2.5 rounded-lg transition-colors ${base}`}>{children}</Link>;
    }
    return <button onClick={signInWithGoogle} className={`w-full px-4 py-2.5 rounded-lg transition-colors ${base}`}>{children}</button>;
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-950 to-gray-900 text-white">
      {/* Nav */}
      <nav className="max-w-5xl mx-auto px-4 py-6 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <span className="text-2xl">🎬</span>
          <span className="text-xl font-bold bg-gradient-to-r from-violet-400 to-purple-500 bg-clip-text text-transparent">
            SupaCam
          </span>
        </Link>
        <div className="flex items-center gap-3">
          <LangToggle />
          {user ? (
            <Link href="/studio" className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors">
              {lang === 'ko' ? '스튜디오' : 'Studio'}
            </Link>
          ) : (
            <button onClick={signInWithGoogle} className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-sm font-medium transition-colors">
              {lang === 'ko' ? '시작하기' : 'Get Started'}
            </button>
          )}
        </div>
      </nav>

      {/* Header */}
      <section className="max-w-4xl mx-auto px-4 pt-12 pb-8 text-center">
        <h1 className="text-4xl font-extrabold">{lang === 'ko' ? '요금제' : 'Pricing'}</h1>
        <p className="mt-4 text-gray-400">
          {lang === 'ko'
            ? '멀티캠 · 타임라인캠 각 2회 무료. 더 많이 촬영하려면 Plus로.'
            : '2 free sessions per mode. Upgrade to Plus for unlimited.'}
        </p>
      </section>

      {/* Plans */}
      <section className="max-w-3xl mx-auto px-4 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Free */}
          <div className="rounded-2xl border border-gray-800 bg-gray-900/50 p-8">
            <h3 className="text-xl font-bold">{PLANS.free.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-5xl font-extrabold">$0</span>
            </div>
            <p className="mt-3 text-sm text-gray-400">{PLANS.free.description[lang]}</p>
            <ul className="mt-6 space-y-3">
              {PLANS.free.features[lang].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-green-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <ActionButton variant="outline">{lang === 'ko' ? '무료로 시작' : 'Start Free'}</ActionButton>
            </div>
          </div>

          {/* Plus */}
          <div className="rounded-2xl border-2 border-violet-600 bg-gray-900/50 p-8 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-violet-600 text-xs font-bold">
              {lang === 'ko' ? '추천' : 'Best Value'}
            </div>
            <h3 className="text-xl font-bold">{PLANS.plus.name}</h3>
            <div className="mt-4 flex items-baseline gap-1">
              <span className="text-5xl font-extrabold">${PLANS.plus.price}</span>
              <span className="text-gray-400">{lang === 'ko' ? '/월' : '/mo'}</span>
            </div>
            <p className="mt-3 text-sm text-gray-400">{PLANS.plus.description[lang]}</p>
            <ul className="mt-6 space-y-3">
              {PLANS.plus.features[lang].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                  <span className="text-violet-400">&#10003;</span> {f}
                </li>
              ))}
            </ul>
            <div className="mt-8">
              <ActionButton variant="primary">{lang === 'ko' ? 'Plus 시작하기' : 'Start Plus'}</ActionButton>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="max-w-2xl mx-auto px-4 pb-16">
        <h2 className="text-xl font-bold text-center mb-8">{lang === 'ko' ? '자주 묻는 질문' : 'FAQ'}</h2>
        <div className="space-y-4">
          <div className="bg-gray-900/50 rounded-xl p-5 border border-gray-800">
            <h3 className="font-semibold text-sm">
              {lang === 'ko' ? '무료로 얼마나 사용할 수 있나요?' : 'How much can I use for free?'}
            </h3>
            <p className="mt-2 text-sm text-gray-400">
              {lang === 'ko'
                ? '멀티캠 2회, 타임라인캠 2회까지 무료로 이용할 수 있습니다. 무료 촬영을 모두 사용한 후 Plus로 업그레이드하면 무제한으로 촬영할 수 있습니다.'
                : 'You get 2 MultiCam sessions and 2 Timeline Cam sessions for free. After using all free sessions, upgrade to Plus for unlimited recording.'}
            </p>
          </div>
          <div className="bg-gray-900/50 rounded-xl p-5 border border-gray-800">
            <h3 className="font-semibold text-sm">
              {lang === 'ko' ? '멀티캠과 타임라인캠의 차이는?' : "What's the difference between MultiCam and Timeline Cam?"}
            </h3>
            <p className="mt-2 text-sm text-gray-400">
              {lang === 'ko'
                ? '멀티캠은 여러 기기로 동시에 촬영하여 AI가 교차편집합니다. 타임라인캠은 촬영/중단을 자유롭게 하면서 모든 영상이 하나의 타임라인에 자동 정렬됩니다.'
                : 'MultiCam records simultaneously from multiple devices, and AI creates cross-cuts. Timeline Cam lets you start and stop freely, with all footage auto-aligned on a single timeline.'}
            </p>
          </div>
          <div className="bg-gray-900/50 rounded-xl p-5 border border-gray-800">
            <h3 className="font-semibold text-sm">
              {lang === 'ko' ? '구독을 취소하면 어떻게 되나요?' : 'What happens if I cancel my subscription?'}
            </h3>
            <p className="mt-2 text-sm text-gray-400">
              {lang === 'ko'
                ? '현재 결제 기간 종료까지 Plus 기능을 이용할 수 있으며, 이후 Free로 전환됩니다. 기존 편집 결과물은 삭제되지 않습니다.'
                : 'You can continue using Plus features until the end of your current billing period, then you\'ll switch to Free. Your existing edits won\'t be deleted.'}
            </p>
          </div>
          <div className="bg-gray-900/50 rounded-xl p-5 border border-gray-800">
            <h3 className="font-semibold text-sm">
              {lang === 'ko' ? '환불이 가능한가요?' : 'Can I get a refund?'}
            </h3>
            <p className="mt-2 text-sm text-gray-400">
              {lang === 'ko'
                ? <>구독 시작 후 7일 이내에 서비스를 이용하지 않은 경우 전액 환불이 가능합니다. 자세한 내용은 <Link href="/refund" className="text-violet-400 hover:text-violet-300 underline">환불 정책</Link>을 확인하세요.</>
                : <>Full refunds are available within 7 days of subscription if you haven&apos;t used the service. See our <Link href="/refund" className="text-violet-400 hover:text-violet-300 underline">refund policy</Link> for details.</>}
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-800 py-8">
        <div className="max-w-4xl mx-auto px-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-sm text-gray-500">&copy; 2026 SupaCam. Payments by Paddle.</p>
            <div className="flex items-center gap-4 text-sm">
              <Link href="/legal/terms" className="text-gray-500 hover:text-gray-300 transition-colors">Terms</Link>
              <Link href="/privacy" className="text-gray-500 hover:text-gray-300 transition-colors">Privacy</Link>
              <Link href="/refund" className="text-gray-500 hover:text-gray-300 transition-colors">Refund</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
