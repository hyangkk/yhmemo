import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Sign In',
  description: 'Sign in to SupaCam to start recording and editing with AI.',
  openGraph: { title: 'SupaCam — Sign In', siteName: 'SupaCam' },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
