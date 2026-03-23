import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — AI Multi-Camera Auto Editing',
  description: 'Record with multiple cameras and let AI automatically edit your footage. MultiCam for simultaneous shooting, Timeline Cam for continuous recording.',
  keywords: ['SupaCam', 'multi-camera', 'AI video editing', 'multicam', 'timeline cam', 'auto editing'],
  authors: [{ name: 'SupaCam' }],
  openGraph: {
    title: 'SupaCam — AI Multi-Camera Auto Editing',
    description: 'Multiple cameras, one video. AI picks the best shots and creates a polished final video.',
    type: 'website',
    siteName: 'SupaCam',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'SupaCam — AI Multi-Camera Auto Editing',
    description: 'Multiple cameras, one video. Edited by AI automatically.',
  },
};

export default function SupaCamHomeLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
