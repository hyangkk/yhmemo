import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — AI 다중 카메라 자동 편집',
  description:
    '여러 대의 카메라로 촬영한 영상을 AI가 자동으로 교차 편집합니다. 무료로 시작하세요.',
  keywords: ['SupaCam', '영상 편집', 'AI 편집', '다중 카메라', '교차편집', '멀티캠'],
  openGraph: {
    title: 'SupaCam — AI 다중 카메라 자동 편집',
    description: '여러 대의 카메라 영상을 AI가 자동으로 교차 편집합니다.',
    type: 'website',
    locale: 'ko_KR',
    siteName: 'SupaCam',
  },
};

export default function SupaCamHomeLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
