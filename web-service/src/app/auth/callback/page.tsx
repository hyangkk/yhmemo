'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { getBrowserSupabase } from '@/lib/auth';

export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    const sb = getBrowserSupabase();
    // URL hash에서 세션 토큰 추출 (Supabase가 자동 처리)
    // hash fragment에서 토큰을 Supabase가 자동 처리하도록 대기
    const handleAuth = async () => {
      // hash에 access_token이 있으면 Supabase가 자동으로 세션 설정
      const { data: { session } } = await sb.auth.getSession();
      if (session) {
        router.replace('/projects');
        return;
      }
      // 아직 세션이 없으면 잠시 대기 후 재시도
      let attempts = 0;
      const checkSession = setInterval(async () => {
        attempts++;
        const { data: { session: s } } = await sb.auth.getSession();
        if (s) {
          clearInterval(checkSession);
          router.replace('/projects');
        } else if (attempts > 20) {
          clearInterval(checkSession);
          router.replace('/studio');
        }
      }, 500);
    };
    handleAuth();
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
