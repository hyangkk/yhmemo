import type { Metadata } from "next";
import FeedbackButton from "@/components/FeedbackButton";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 뉴스 브리핑 — 매일 AI가 골라주는 핵심 뉴스",
  description:
    "AI 에이전트가 24시간 뉴스를 수집하고, 분석하고, 핵심만 골라드립니다. 매일 자동 업데이트되는 개인화 뉴스 브리핑 서비스.",
  keywords: ["AI 뉴스", "뉴스 브리핑", "AI 큐레이션", "자동 뉴스", "뉴스 요약", "AI 에이전트"],
  authors: [{ name: "AI News Briefing" }],
  robots: { index: true, follow: true },
  openGraph: {
    title: "AI 뉴스 브리핑 — 오늘 5개만 읽으면 끝",
    description: "AI가 24시간 수집·선별한 핵심 뉴스. 다 읽으면 오늘 뉴스는 끝.",
    type: "website",
    locale: "ko_KR",
    siteName: "AI 뉴스 브리핑",
  },
  twitter: {
    card: "summary_large_image",
    title: "AI 뉴스 브리핑 — 오늘 5개만 읽으면 끝",
    description: "AI가 24시간 수집·선별한 핵심 뉴스",
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
        <meta name="theme-color" content="#f59e0b" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="뉴스브리핑" />
      </head>
      <body className="antialiased">
        {children}
        <FeedbackButton />
      </body>
    </html>
  );
}
