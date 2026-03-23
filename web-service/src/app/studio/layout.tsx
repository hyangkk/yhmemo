import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — Studio',
  description: 'Record with multiple cameras and get AI-edited videos. MultiCam and Timeline Cam modes available.',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'SupaCam',
  },
  openGraph: { title: 'SupaCam — Studio', siteName: 'SupaCam' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover',
};

export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
