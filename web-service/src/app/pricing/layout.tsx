import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'SupaCam — 요금제',
  description: 'SupaCam Free와 Plus 요금제를 비교하고 시작하세요. 무료로 시작, 필요할 때 업그레이드.',
  openGraph: {
    title: 'SupaCam — 요금제',
    description: 'AI 다중 카메라 자동 편집 서비스 SupaCam의 요금제 안내.',
    type: 'website',
    siteName: 'SupaCam',
  },
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
