'use client';

import { useState, useEffect, createContext, useContext, useCallback } from 'react';
import React from 'react';

export type Lang = 'ko' | 'en';

interface LangContextType {
  lang: Lang;
  setLang: (lang: Lang) => void;
}

const LangContext = createContext<LangContextType>({
  lang: 'en',
  setLang: () => {},
});

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>('en');

  useEffect(() => {
    const stored = localStorage.getItem('supacam_lang') as Lang | null;
    if (stored === 'ko' || stored === 'en') {
      setLangState(stored);
    } else {
      const browserLang = navigator.language || '';
      setLangState(browserLang.startsWith('ko') ? 'ko' : 'en');
    }
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem('supacam_lang', l);
  }, []);

  return React.createElement(
    LangContext.Provider,
    { value: { lang, setLang } },
    children
  );
}

export function useLang() {
  return useContext(LangContext);
}

// 언어 전환 버튼 컴포넌트
export function LangToggle({ className }: { className?: string }) {
  const { lang, setLang } = useLang();
  return (
    <button
      onClick={() => setLang(lang === 'ko' ? 'en' : 'ko')}
      className={className || 'text-xs text-gray-400 hover:text-white border border-gray-700 rounded-md px-2 py-1 transition-colors'}
    >
      {lang === 'ko' ? 'EN' : '한국어'}
    </button>
  );
}
