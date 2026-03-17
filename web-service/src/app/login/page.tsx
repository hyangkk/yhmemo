'use client';

import { useAuth } from '@/lib/auth';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export default function LoginPage() {
  const { user, loading, signInWithGoogle } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && user) {
      router.replace('/projects');
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-black text-white flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-4">
      <div className="max-w-sm w-full space-y-8 text-center">
        <div>
          <h1 className="text-3xl font-bold">멀티캠 스튜디오</h1>
          <p className="text-gray-400 mt-2">여러 카메라로 촬영하고 AI가 자동 편집</p>
        </div>

        <div className="space-y-3">
          <button
            onClick={signInWithGoogle}
            className="w-full flex items-center justify-center gap-3 bg-white text-black py-3 px-6 rounded-xl font-semibold hover:bg-gray-100 transition"
          >
            <svg className="w-5 h-5" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Google로 시작하기
          </button>

          <button
            onClick={() => router.push('/studio')}
            className="w-full bg-gray-800 hover:bg-gray-700 py-3 px-6 rounded-xl text-sm transition text-gray-300"
          >
            로그인 없이 기존 스튜디오 사용
          </button>
        </div>

        <p className="text-gray-600 text-xs">
          로그인하면 프로젝트를 만들고 여러 번 촬영할 수 있어요
        </p>
      </div>
    </div>
  );
}
