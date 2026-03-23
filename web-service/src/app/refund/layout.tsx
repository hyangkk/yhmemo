import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Refund Policy',
  description: 'SupaCam refund policy. Full refund within 7 days if unused.',
  openGraph: { title: 'SupaCam — Refund Policy', siteName: 'SupaCam' },
};

export default function RefundLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
