'use client';

import { AuthProvider } from '@/lib/auth';
import { LangProvider } from '@/lib/i18n';

export function AuthWrapper({ children }: { children: React.ReactNode }) {
  return (
    <LangProvider>
      <AuthProvider>{children}</AuthProvider>
    </LangProvider>
  );
}
