'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth, getBrowserSupabase } from '@/lib/auth';
import { useLang } from '@/lib/i18n';

export default function ConsentPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { lang } = useLang();
  const [agreed, setAgreed] = useState({ terms: false, privacy: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const isSupaCam = typeof window !== 'undefined' && window.location.hostname.includes('supacam');
  const redirectPath = isSupaCam ? '/studio' : '/projects';

  const allAgreed = agreed.terms && agreed.privacy;

  const t = {
    title: lang === 'ko' ? 'SupaCam' : 'SupaCam',
    welcome: lang === 'ko' ? '환영합니다!' : 'Welcome!',
    subtitle: lang === 'ko'
      ? '서비스 이용을 위해 아래 약관에 동의해 주세요.'
      : 'Please agree to the following terms to continue.',
    termsLabel: lang === 'ko'
      ? '이용약관에 동의합니다 (필수)'
      : 'I agree to the Terms of Service (required)',
    privacyLabel: lang === 'ko'
      ? '개인정보 처리방침에 동의합니다 (필수)'
      : 'I agree to the Privacy Policy (required)',
    termsLink: lang === 'ko' ? '이용약관 보기' : 'View Terms',
    privacyLink: lang === 'ko' ? '개인정보 처리방침 보기' : 'View Privacy Policy',
    agreeAll: lang === 'ko' ? '전체 동의' : 'Agree to all',
    continue: lang === 'ko' ? '시작하기' : 'Get Started',
    errorMsg: lang === 'ko' ? '처리 중 오류가 발생했습니다. 다시 시도해 주세요.' : 'Something went wrong. Please try again.',
    loginFirst: lang === 'ko' ? '로그인이 필요합니다. 잠시만 기다려 주세요...' : 'Sign-in required. Please wait...',
  };

  const handleSubmit = async () => {
    if (!allAgreed || loading) return;
    setLoading(true);
    setError('');
    try {
      const supabase = getBrowserSupabase();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) {
        setError(t.loginFirst);
        setLoading(false);
        return;
      }

      const res = await fetch('/api/auth/consent', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${session.access_token}` },
      });

      if (!res.ok) throw new Error();
      router.replace(redirectPath);
    } catch {
      setError(t.errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const toggleAll = () => {
    const newVal = !(agreed.terms && agreed.privacy);
    setAgreed({ terms: newVal, privacy: newVal });
  };

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center p-4">
      <div className="max-w-md w-full space-y-6">
        {/* 헤더 */}
        <div className="text-center space-y-2">
          <div className="text-4xl mb-4">🎬</div>
          <h1 className="text-2xl font-bold">{t.title}</h1>
          <h2 className="text-lg text-gray-300">{t.welcome}</h2>
          {user && (
            <p className="text-sm text-gray-500">{user.email}</p>
          )}
          <p className="text-sm text-gray-400 mt-2">{t.subtitle}</p>
        </div>

        {/* 약관 동의 */}
        <div className="bg-gray-900 rounded-2xl p-5 space-y-4">
          {/* 전체 동의 */}
          <button
            onClick={toggleAll}
            className="w-full flex items-center gap-3 p-3 rounded-xl bg-gray-800 hover:bg-gray-750 transition text-left"
          >
            <span className={`w-5 h-5 rounded border-2 flex items-center justify-center shrink-0 transition ${
              allAgreed ? 'bg-violet-600 border-violet-600' : 'border-gray-600'
            }`}>
              {allAgreed && <span className="text-white text-xs">✓</span>}
            </span>
            <span className="font-medium text-sm">{t.agreeAll}</span>
          </button>

          <div className="h-px bg-gray-800" />

          {/* 이용약관 */}
          <div className="flex items-start gap-3">
            <button
              onClick={() => setAgreed(p => ({ ...p, terms: !p.terms }))}
              className="mt-0.5 shrink-0"
            >
              <span className={`w-5 h-5 rounded border-2 flex items-center justify-center transition ${
                agreed.terms ? 'bg-violet-600 border-violet-600' : 'border-gray-600'
              }`}>
                {agreed.terms && <span className="text-white text-xs">✓</span>}
              </span>
            </button>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-300">{t.termsLabel}</p>
              <a href="/legal/terms" target="_blank" className="text-xs text-violet-400 hover:text-violet-300 underline">
                {t.termsLink} →
              </a>
            </div>
          </div>

          {/* 개인정보 처리방침 */}
          <div className="flex items-start gap-3">
            <button
              onClick={() => setAgreed(p => ({ ...p, privacy: !p.privacy }))}
              className="mt-0.5 shrink-0"
            >
              <span className={`w-5 h-5 rounded border-2 flex items-center justify-center transition ${
                agreed.privacy ? 'bg-violet-600 border-violet-600' : 'border-gray-600'
              }`}>
                {agreed.privacy && <span className="text-white text-xs">✓</span>}
              </span>
            </button>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-gray-300">{t.privacyLabel}</p>
              <a href="/privacy" target="_blank" className="text-xs text-violet-400 hover:text-violet-300 underline">
                {t.privacyLink} →
              </a>
            </div>
          </div>
        </div>

        {error && (
          <p className="text-red-400 text-center text-sm">{error}</p>
        )}

        {/* 시작 버튼 */}
        <button
          onClick={handleSubmit}
          disabled={!allAgreed || loading}
          className={`w-full py-3 rounded-xl font-semibold text-sm transition ${
            allAgreed
              ? 'bg-violet-600 hover:bg-violet-500 text-white'
              : 'bg-gray-800 text-gray-500 cursor-not-allowed'
          }`}
        >
          {loading ? '...' : t.continue}
        </button>
      </div>
    </div>
  );
}
