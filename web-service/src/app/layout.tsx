import type { Metadata } from "next";
import "./globals.css";
import { AuthWrapper } from "./auth-wrapper";

export const metadata: Metadata = {
  title: "AI 전략실 — 데이터 기반 전략 인사이트",
  description:
    "각 분야 전문 AI 에이전트가 24시간 정보를 수집·분석하고 데이터 기반 전략 인사이트를 제공합니다.",
  keywords: ["AI 전략실", "AI 투자", "투자 시그널", "시장 분석", "AI 에이전트", "실시간 분석", "헬스케어 전략", "마케팅 전략"],
  authors: [{ name: "AI Strategy Room" }],
  robots: { index: true, follow: true },
  openGraph: {
    title: "AI 전략실 — 데이터 기반 전략 인사이트",
    description: "각 분야 전문 AI 에이전트가 24시간 정보를 수집·분석하고 전략 인사이트를 제공합니다.",
    type: "website",
    locale: "ko_KR",
    siteName: "AI 전략실",
  },
  twitter: {
    card: "summary_large_image",
    title: "AI 전략실 — 데이터 기반 전략 인사이트",
    description: "각 분야 전문 AI 에이전트가 24시간 전략 인사이트 제공",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="theme-color" content="#7c3aed" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="SupaCam" />
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎬</text></svg>" />
      </head>
      <body className="antialiased">
        <AuthWrapper>{children}</AuthWrapper>
      </body>
    </html>
  );
}
