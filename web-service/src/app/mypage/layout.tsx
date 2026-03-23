import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — My Page',
  description: 'Manage your SupaCam account and subscription.',
  openGraph: { title: 'SupaCam — My Page', siteName: 'SupaCam' },
};

export default function MyPageLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
