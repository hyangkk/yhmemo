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

    // onAuthStateChange만 사용 (Supabase 권장 패턴)
    // getSession()은 새로고침 시 localStorage 로드 전에 null을 반환할 수 있어 제거
    const { data: { subscription } } = sb.auth.onAuthStateChange(async (event, session) => {
      try {
        if (session?.user) {
          const { data: profile } = await sb.from('profiles').select('*').eq('id', session.user.id).single();
          setUser(profile || null);
        } else {
          setUser(null);
        }
      } catch (e) {
        console.error('인증 상태 처리 실패:', e);
        setUser(null);
      } finally {
        setLoading(false);
      }
    });

    return () => subscription.unsubscribe();
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
