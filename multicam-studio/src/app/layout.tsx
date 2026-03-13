import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '멀티캠 스튜디오',
  description: '여러 대의 카메라로 동시 촬영하고 자동 편집된 영상을 받아보세요',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: '멀티캠 스튜디오',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: 'cover',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
