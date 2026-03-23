import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Privacy Policy',
  description: 'SupaCam privacy policy. How we collect, use, and protect your data.',
  openGraph: { title: 'SupaCam — Privacy Policy', siteName: 'SupaCam' },
};

export default function PrivacyLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
