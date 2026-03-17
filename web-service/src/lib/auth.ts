'use client';

import { createClient } from '@supabase/supabase-js';
import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import React from 'react';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// 브라우저용 Supabase 클라이언트 (implicit flow)
let browserClient: ReturnType<typeof createClient> | null = null;
export function getBrowserSupabase() {
  if (!browserClient) {
    browserClient = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        flowType: 'implicit',
        detectSessionInUrl: true,
      },
    });
  }
  return browserClient;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  plan: string;
}

interface AuthContextType {
  user: UserProfile | null;
  loading: boolean;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  signInWithGoogle: async () => {},
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sb = getBrowserSupabase();
    let ignore = false;

    // 프로필 조회 (onAuthStateChange 콜백 밖에서 실행 — 데드락 방지)
    // Supabase 쿼리 빌더는 PromiseLike(.catch 없음)이므로 Promise.resolve()로 감싸기
    const fetchProfile = (userId: string) => {
      Promise.resolve(sb.from('profiles').select('*').eq('id', userId).single())
        .then(({ data: profile }) => {
          if (!ignore) {
            setUser(profile || null);
            setLoading(false);
          }
        })
        .catch(() => {
          if (!ignore) {
            setUser(null);
            setLoading(false);
          }
        });
    };

    // ⚠️ 콜백은 반드시 동기 함수! async 쓰면 Supabase 내부 락 데드락 발생
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, session) => {
      if (ignore) return;
      if (session?.user) {
        fetchProfile(session.user.id);
      } else {
        setUser(null);
        setLoading(false);
      }
    });

    return () => {
      ignore = true;
      subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    const sb = getBrowserSupabase();
    await sb.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: 'https://web-service-ruby.vercel.app/auth/callback',
      },
    });
  }, []);

  const signOut = useCallback(async () => {
    const sb = getBrowserSupabase();
    await sb.auth.signOut();
    setUser(null);
  }, []);

  return React.createElement(
    AuthContext.Provider,
    { value: { user, loading, signInWithGoogle, signOut } },
    children
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
