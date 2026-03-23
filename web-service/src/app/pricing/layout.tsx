import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Pricing',
  description: '2 free sessions per mode. Upgrade to Plus ($9/mo) for unlimited MultiCam and Timeline Cam.',
  openGraph: {
    title: 'SupaCam — Pricing',
    description: 'Start free with 2 sessions per mode. Upgrade for unlimited.',
    siteName: 'SupaCam',
  },
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
