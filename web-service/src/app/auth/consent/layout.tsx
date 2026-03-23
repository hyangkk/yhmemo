import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Terms & Conditions',
  description: 'Agree to SupaCam terms of service and privacy policy to get started.',
  openGraph: {
    title: 'SupaCam — Terms & Conditions',
    description: 'Agree to terms to start using SupaCam.',
    siteName: 'SupaCam',
  },
};

export default function ConsentLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
