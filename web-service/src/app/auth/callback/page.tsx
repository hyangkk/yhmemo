'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getBrowserSupabase } from '@/lib/auth';

export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    const sb = getBrowserSupabase();
    // URL hash에서 세션 토큰 추출 (Supabase가 자동 처리)
    sb.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        router.replace('/projects');
      } else {
        // hash fragment에서 토큰 파싱 대기
        const checkSession = setInterval(async () => {
          const { data: { session: s } } = await sb.auth.getSession();
          if (s) {
            clearInterval(checkSession);
            router.replace('/projects');
          }
        }, 500);
        setTimeout(() => {
          clearInterval(checkSession);
          router.replace('/login');
        }, 10000);
      }
    });
  }, [router]);

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-gray-400">로그인 처리 중...</p>
      </div>
    </div>
  );
}
