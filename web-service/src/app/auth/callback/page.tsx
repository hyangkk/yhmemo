'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { getBrowserSupabase } from '@/lib/auth';
import { Suspense } from 'react';

function AuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const sb = getBrowserSupabase();
    const code = searchParams.get('code');

    const handleAuth = async () => {
      // PKCE flow: ?code= query parameter
      if (code) {
        await sb.auth.exchangeCodeForSession(code);
        router.replace('/projects');
        return;
      }

      // Implicit flow fallback: #access_token= hash fragment
      if (window.location.hash.includes('access_token')) {
        // Supabase 클라이언트가 hash에서 자동으로 세션 설정
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
    };

    handleAuth();
  }, [router, searchParams]);

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-gray-400">로그인 처리 중...</p>
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
