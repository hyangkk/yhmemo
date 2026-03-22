'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getBrowserSupabase } from '@/lib/auth';

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sb = getBrowserSupabase();

    // supacam 도메인 여부에 따라 리다이렉트 경로 결정
    const isSupaCam = typeof window !== 'undefined' && window.location.hostname.includes('supacam');
    const redirectPath = isSupaCam ? '/studio' : '/projects';

    // Supabase가 URL hash에서 세션을 자동으로 감지 (detectSessionInUrl: true)
    // onAuthStateChange로 세션 설정 완료를 감지
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, session) => {
      // INITIAL_SESSION: URL hash에서 세션 복원, SIGNED_IN: OAuth 콜백 처리
      if ((event === 'SIGNED_IN' || event === 'INITIAL_SESSION') && session) {
        router.replace(redirectPath);
      }
    });

    // 타임아웃: 10초 내 로그인 안 되면 에러 표시
    const timeout = setTimeout(() => {
      setError('로그인 처리 시간 초과. 다시 시도해주세요.');
      setTimeout(() => router.replace(redirectPath), 2000);
    }, 10000);

    return () => {
      subscription.unsubscribe();
      clearTimeout(timeout);
    };
  }, [router]);

  return (
    <div className="min-h-screen bg-black text-white flex items-center justify-center">
      <div className="text-center">
        {error ? (
          <>
            <p className="text-red-400 mb-2">{error}</p>
            <p className="text-gray-500 text-sm">이동 중...</p>
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
