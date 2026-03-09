import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI 시장 분석 — 실시간 크로스 분석 | AI 투자전략실",
  description:
    "AI가 뉴스와 시장 데이터를 크로스 분석하여 인사이트를 제공합니다. 비트코인, 이더리움, 금 실시간 시세 + AI 분석.",
  openGraph: {
    title: "AI 시장 분석 — 뉴스 x 시장 크로스 분석",
    description:
      "AI가 뉴스와 시장 데이터를 결합 분석. 비트코인, 이더리움, 금 실시간 시세와 인사이트.",
    type: "website",
    locale: "ko_KR",
  },
};

export default function MarketLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
