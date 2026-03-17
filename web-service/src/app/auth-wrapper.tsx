'use client';

import { AuthProvider } from '@/lib/auth';

export function AuthWrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
