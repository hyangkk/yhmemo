'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth, getBrowserSupabase } from '@/lib/auth';
import { PLANS } from '@/lib/paddle';
import { useLang, LangToggle } from '@/lib/i18n';
import { usePaddle } from '@/lib/usePaddle';

export default function MyPage() {
  const { user, loading: authLoading, signOut, refreshProfile } = useAuth();
  const router = useRouter();
  const { lang } = useLang();
  const [subscribing, setSubscribing] = useState(false);
  const [plan, setPlan] = useState<string>('free');
  const [message, setMessage] = useState('');
  const [deleting, setDeleting] = useState(false);

  const { openCheckout } = usePaddle({
    userId: user?.id,
    userEmail: user?.email,
    onSuccess: async (transactionId) => {
      setSubscribing(true);
      await fetch('/api/paddle/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId: user?.id,
          transactionId,
          plan: 'plus',
        }),
      });
      await refreshProfile();
      setPlan('plus');
      setMessage(lang === 'ko' ? 'Plus 구독이 활성화되었습니다!' : 'Plus subscription activated!');
      setSubscribing(false);
    },
  });

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

  const handleSubscribe = () => {
    openCheckout();
  };

  const handleUnsubscribe = async () => {
    const confirmMsg = lang === 'ko'
      ? '정말 구독을 취소하시겠어요?\n무료 요금제로 전환됩니다.'
      : "Cancel your subscription?\nYou'll switch to the Free plan.";
    if (!confirm(confirmMsg)) return;
    setSubscribing(true);
    setMessage('');
    try {
      const token = await getToken();
      const res = await fetch('/api/unsubscribe', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('unsubscribe failed');
      await refreshProfile();
      setPlan('free');
      setMessage(lang === 'ko' ? '구독이 취소되었습니다. 무료 요금제로 전환되었어요.' : 'Subscription cancelled. Switched to Free plan.');
    } catch {
      setMessage(lang === 'ko' ? '구독 취소 처리 중 오류가 발생했습니다.' : 'Error cancelling subscription.');
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
            {lang === 'ko' ? '← 뒤로' : '← Back'}
          </button>
          <h1 className="text-lg font-bold">{lang === 'ko' ? '마이페이지' : 'My Page'}</h1>
          <LangToggle />
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
          <h2 className="text-base font-bold">{lang === 'ko' ? '구독 관리' : 'Subscription'}</h2>

          {isPlus ? (
            <div className="space-y-3">
              <div className="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-purple-300">{lang === 'ko' ? 'Plus 구독 중' : 'Plus Active'}</p>
                    <p className="text-sm text-gray-400 mt-1">${PLANS.plus.price}{lang === 'ko' ? '/월' : '/mo'}</p>
                  </div>
                  <span className="text-purple-400 text-2xl">&#10003;</span>
                </div>
              </div>
              <ul className="space-y-1.5">
                {PLANS.plus.features[lang].map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                    <span className="text-purple-400">&#10003;</span> {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={handleUnsubscribe}
                disabled={subscribing}
                className="w-full text-gray-500 hover:text-red-400 disabled:text-gray-700 py-2 text-xs transition cursor-pointer"
              >
                {subscribing ? (lang === 'ko' ? '처리 중...' : 'Processing...') : (lang === 'ko' ? '구독 취소' : 'Cancel')}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-gray-800 rounded-xl p-4">
                <p className="text-sm text-gray-400">
                  {lang === 'ko' ? '현재 무료 요금제를 사용 중입니다.' : "You're on the Free plan."}
                </p>
                <p className="text-sm text-gray-500 mt-1">
                  {lang === 'ko' ? '멀티캠 2회, 타임라인캠 2회 이용 가능' : '2 MultiCam + 2 Timeline Cam sessions available'}
                </p>
              </div>

              <div className="border border-purple-500/50 rounded-xl p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-bold text-lg">Plus</p>
                    <p className="text-gray-400 text-sm">{PLANS.plus.description[lang]}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold">${PLANS.plus.price}</p>
                    <p className="text-xs text-gray-500">{lang === 'ko' ? '/월' : '/mo'}</p>
                  </div>
                </div>
                <ul className="space-y-1.5">
                  {PLANS.plus.features[lang].map((f) => (
                    <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                      <span className="text-purple-400">&#10003;</span> {f}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={handleSubscribe}
                  disabled={subscribing}
                  className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 py-3 rounded-xl text-sm font-bold transition cursor-pointer"
                >
                  {subscribing
                    ? (lang === 'ko' ? '처리 중...' : 'Processing...')
                    : (lang === 'ko' ? `Plus 구독하기 — $${PLANS.plus.price}/월` : `Subscribe to Plus — $${PLANS.plus.price}/mo`)}
                </button>
              </div>
            </div>
          )}

          {message && (
            <p className={`text-center text-sm ${message.includes('활성화') || message.includes('activated') ? 'text-green-400' : 'text-red-400'}`}>
              {message}
            </p>
          )}
        </div>

        {/* 계정 관리 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-3">
          <h2 className="text-base font-bold">{lang === 'ko' ? '계정' : 'Account'}</h2>
          <button
            onClick={signOut}
            className="w-full text-left px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-red-400 transition cursor-pointer"
          >
            {lang === 'ko' ? '로그아웃' : 'Sign Out'}
          </button>
          <button
            disabled={deleting}
            onClick={async () => {
              const msg = lang === 'ko'
                ? '정말 탈퇴하시겠어요?\n\n• 모든 데이터가 삭제됩니다\n• 활성 구독이 있으면 즉시 취소됩니다\n• 이 작업은 되돌릴 수 없습니다'
                : "Delete your account?\n\n• All data will be deleted\n• Active subscriptions will be cancelled\n• This cannot be undone";
              if (!confirm(msg)) return;
              const confirmMsg = lang === 'ko' ? '마지막 확인: 정말 탈퇴하시겠어요?' : 'Final confirmation: delete your account?';
              if (!confirm(confirmMsg)) return;
              setDeleting(true);
              try {
                const token = await getToken();
                const res = await fetch('/api/account/delete', {
                  method: 'POST',
                  headers: { Authorization: `Bearer ${token}` },
                });
                if (res.ok) {
                  await signOut();
                  router.replace('/');
                } else {
                  setMessage(lang === 'ko' ? '탈퇴 처리 중 오류가 발생했습니다.' : 'Error deleting account.');
                }
              } catch {
                setMessage(lang === 'ko' ? '탈퇴 처리 중 오류가 발생했습니다.' : 'Error deleting account.');
              } finally {
                setDeleting(false);
              }
            }}
            className="w-full text-left px-4 py-3 rounded-xl bg-gray-800 hover:bg-red-900/30 text-sm text-gray-600 hover:text-red-400 transition cursor-pointer disabled:opacity-50"
          >
            {deleting
              ? (lang === 'ko' ? '처리 중...' : 'Deleting...')
              : (lang === 'ko' ? '회원 탈퇴' : 'Delete Account')}
          </button>
        </div>

        {/* 서비스 정보 */}
        <div className="bg-gray-900 rounded-2xl p-6 space-y-3">
          <h2 className="text-base font-bold">{lang === 'ko' ? '서비스 정보' : 'Service Info'}</h2>
          <div className="grid grid-cols-2 gap-2">
            <Link href="/pricing" className="px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition text-center">
              {lang === 'ko' ? '요금제' : 'Pricing'}
            </Link>
            <Link href="/legal/terms" className="px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition text-center">
              {lang === 'ko' ? '이용약관' : 'Terms'}
            </Link>
            <Link href="/privacy" className="px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition text-center">
              {lang === 'ko' ? '개인정보처리방침' : 'Privacy'}
            </Link>
            <Link href="/refund" className="px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition text-center">
              {lang === 'ko' ? '환불정책' : 'Refund'}
            </Link>
          </div>
          <p className="text-xs text-gray-600 text-center pt-1">ai.agent.yh@gmail.com</p>
        </div>
      </div>
    </div>
  );
}
