'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { getBrowserSupabase } from '@/lib/auth';
import { Suspense } from 'react';

function AuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sb = getBrowserSupabase();
    const code = searchParams.get('code');

    const handleAuth = async () => {
      try {
        // PKCE flow: ?code= query parameter
        if (code) {
          const { error: exchangeError } = await sb.auth.exchangeCodeForSession(code);
          if (exchangeError) {
            console.error('Code exchange error:', exchangeError);
            setError(`코드 교환 실패: ${exchangeError.message}`);
            // 3초 후 studio로 이동
            setTimeout(() => router.replace('/studio'), 3000);
            return;
          }
          router.replace('/projects');
          return;
        }

        // Implicit flow fallback: #access_token= hash fragment
        if (window.location.hash.includes('access_token')) {
          let attempts = 0;
          const checkSession = setInterval(async () => {
            attempts++;
            const { data: { session } } = await sb.auth.getSession();
            if (session) {
              clearInterval(checkSession);
              router.replace('/projects');
            } else if (attempts > 20) {
              clearInterval(checkSession);
              router.replace('/studio');
            }
          }, 500);
          return;
        }

        // 세션 이미 있는 경우
        const { data: { session } } = await sb.auth.getSession();
        if (session) {
          router.replace('/projects');
        } else {
          router.replace('/studio');
        }
      } catch (err) {
        console.error('Auth callback error:', err);
        setError(`인증 오류: ${err instanceof Error ? err.message : String(err)}`);
        setTimeout(() => router.replace('/studio'), 3000);
      }
    };

    handleAuth();
  }, [router, searchParams]);

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center">
      <div className="text-center">
        {error ? (
          <>
            <p className="text-red-400 mb-2">{error}</p>
            <p className="text-gray-500 text-sm">잠시 후 다시 시도합니다...</p>
          </>
        ) : (
          <>
            <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-gray-400">로그인 처리 중...</p>
          </>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto" />
      </div>
    }>
      <AuthCallbackInner />
    </Suspense>
  );
}
