import type { Metadata } from "next";
import FeedbackButton from "@/components/FeedbackButton";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 리딩룸 — 실시간 투자 시그널 + 시장 분석",
  description:
    "AI가 24시간 뉴스·시장·센티먼트를 크로스 분석하여 투자 시그널을 도출합니다. 실시간 리딩룸.",
  keywords: ["AI 투자", "투자 시그널", "시장 분석", "AI 리딩룸", "크립토 분석", "AI 에이전트", "실시간 분석"],
  authors: [{ name: "AI Reading Room" }],
  robots: { index: true, follow: true },
  openGraph: {
    title: "AI 리딩룸 — 실시간 투자 시그널",
    description: "AI가 뉴스×시장×센티먼트를 크로스 분석. 투자 시그널 실시간 도출.",
    type: "website",
    locale: "ko_KR",
    siteName: "AI 리딩룸",
  },
  twitter: {
    card: "summary_large_image",
    title: "AI 리딩룸 — 실시간 투자 시그널",
    description: "AI가 뉴스×시장×센티먼트를 크로스 분석",
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
