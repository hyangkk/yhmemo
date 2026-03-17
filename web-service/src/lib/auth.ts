'use client';

import { createClient } from '@supabase/supabase-js';
import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import React from 'react';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

// 브라우저용 Supabase 클라이언트 (Auth 포함)
let browserClient: ReturnType<typeof createClient> | null = null;
export function getBrowserSupabase() {
  if (!browserClient) {
    browserClient = createClient(supabaseUrl, supabaseAnonKey);
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

    // 현재 세션 확인
    const getSession = async () => {
      const { data: { session } } = await sb.auth.getSession();
      if (session?.user) {
        const { data: profile } = await sb.from('profiles').select('*').eq('id', session.user.id).single();
        setUser(profile || null);
      }
      setLoading(false);
    };
    getSession();

    // Auth 상태 변경 리스너
    const { data: { subscription } } = sb.auth.onAuthStateChange(async (_event, session) => {
      if (session?.user) {
        const { data: profile } = await sb.from('profiles').select('*').eq('id', session.user.id).single();
        setUser(profile || null);
      } else {
        setUser(null);
      }
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const signInWithGoogle = useCallback(async () => {
    const sb = getBrowserSupabase();
    const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || window.location.origin;
    await sb.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: `${siteUrl}/auth/callback`,
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
