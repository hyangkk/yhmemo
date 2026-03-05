import MorningBriefing from "@/components/MorningBriefing";
import Dashboard from "@/components/Dashboard";

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* Hero */}
      <header className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-amber-600/10 to-orange-600/10 dark:from-amber-600/5 dark:to-orange-600/5" />
        <div className="relative max-w-5xl mx-auto px-4 py-12 sm:py-16">
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 text-sm font-medium mb-4">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              AI가 24시간 실시간 운영 중
            </div>

            <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-900 dark:text-white tracking-tight">
              오늘{" "}
              <span className="bg-gradient-to-r from-amber-500 to-orange-600 bg-clip-text text-transparent">
                5개만
              </span>{" "}
              읽으면 끝
            </h1>

            <p className="mt-3 text-base sm:text-lg text-gray-600 dark:text-gray-300 max-w-xl mx-auto">
              AI가 수십 개 뉴스 중 꼭 알아야 할 5개만 골라드립니다.
              <br />
              다 읽으면 오늘 뉴스는 끝. 더 이상 스크롤 없이.
            </p>

            <div className="mt-6 flex items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400">
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                AI 선별
              </div>
              <div className="w-1 h-1 rounded-full bg-gray-300" />
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                5개면 충분
              </div>
              <div className="w-1 h-1 rounded-full bg-gray-300" />
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                2분 완독
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Morning Briefing - 메인 경험 */}
      <MorningBriefing />

      {/* 구분선 */}
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-800" />
          </div>
          <div className="relative flex justify-center">
            <span className="px-4 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900 dark:to-gray-950 text-sm text-gray-400">
              전체 뉴스 피드
            </span>
          </div>
        </div>
      </div>

      {/* 기존 대시보드 (전체 뉴스) */}
      <Dashboard />

      {/* Footer */}
      <footer className="max-w-5xl mx-auto px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-500">
        <p>
          Powered by AI Agents — 자율운영 에이전트 시스템이 24시간 운영합니다.
        </p>
        <p className="mt-1">
          © 2026 AI News Briefing. Built with Next.js + Supabase.
        </p>
      </footer>
    </main>
  );
}
