import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 뉴스 브리핑 — 매일 AI가 골라주는 핵심 뉴스",
  description:
    "AI 에이전트가 24시간 뉴스를 수집하고, 분석하고, 핵심만 골라드립니다. 매일 자동 업데이트되는 개인화 뉴스 브리핑 서비스.",
  openGraph: {
    title: "AI 뉴스 브리핑",
    description: "AI가 24시간 수집·선별한 핵심 뉴스",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
