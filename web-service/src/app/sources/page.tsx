import Link from "next/link";
import DataSources from "@/components/DataSources";

export const metadata = {
  title: "정보 수집 현황 — AI 리딩룸",
  description: "AI 리딩룸이 수집 중인 데이터 소스와 수집 예정 소스를 확인하세요.",
};

export default function SourcesPage() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* Header */}
      <header className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-violet-600/10 to-purple-600/10 dark:from-violet-600/5 dark:to-purple-600/5" />
        <div className="relative max-w-5xl mx-auto px-4 py-10 sm:py-14">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors mb-6"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
            홈으로
          </Link>

          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-sm font-medium mb-4">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              실시간 수집 중
            </div>

            <h1 className="text-3xl sm:text-4xl font-extrabold text-gray-900 dark:text-white tracking-tight">
              정보 수집{" "}
              <span className="bg-gradient-to-r from-violet-500 to-purple-600 bg-clip-text text-transparent">
                현황
              </span>
            </h1>

            <p className="mt-3 text-base text-gray-600 dark:text-gray-300 max-w-xl mx-auto">
              AI 리딩룸이 어떤 데이터를 수집하고 분석하는지, 그리고 앞으로 어떤
              소스를 추가할 예정인지 한눈에 확인하세요.
            </p>
          </div>
        </div>
      </header>

      <DataSources />

      {/* Footer */}
      <footer className="max-w-5xl mx-auto px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-500">
        <p>
          Powered by AI Agents — 자율운영 에이전트 시스템이 24시간 운영합니다.
        </p>
      </footer>
    </main>
  );
}
