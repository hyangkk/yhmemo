import Link from "next/link";
import MorningBriefing from "@/components/MorningBriefing";
import MarketDashboard from "@/components/MarketDashboard";
import TrendingTopics from "@/components/TrendingTopics";
import InvestSignal from "@/components/InvestSignal";
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
              AI{" "}
              <span className="bg-gradient-to-r from-violet-500 to-purple-600 bg-clip-text text-transparent">
                리딩룸
              </span>
            </h1>

            <p className="mt-3 text-base sm:text-lg text-gray-600 dark:text-gray-300 max-w-xl mx-auto">
              실시간 시장 시그널 포착 + 펀더멘탈 분석 + 투자 전략 제시
              <br />
              AI가 24시간 뉴스와 시장을 크로스 분석합니다.
            </p>

            <div className="mt-6 flex items-center justify-center gap-4 text-sm text-gray-500 dark:text-gray-400">
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                실시간 시그널
              </div>
              <div className="w-1 h-1 rounded-full bg-gray-300" />
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
                크로스 분석
              </div>
              <div className="w-1 h-1 rounded-full bg-gray-300" />
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                24시간 운영
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Morning Briefing - 메인 경험 */}
      <MorningBriefing />

      {/* 트렌드 토픽 */}
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-800" />
          </div>
          <div className="relative flex justify-center">
            <span className="px-4 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900 dark:to-gray-950 text-sm text-gray-400">
              지금 뜨는 토픽
            </span>
          </div>
        </div>
      </div>
      <TrendingTopics />

      {/* 구분선 - 시장 현황 */}
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-800" />
          </div>
          <div className="relative flex justify-center">
            <span className="px-4 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900 dark:to-gray-950 text-sm text-gray-400">
              실시간 시장 현황
            </span>
          </div>
        </div>
      </div>

      {/* 투자/시장 대시보드 */}
      <MarketDashboard />

      {/* 구분선 - 투자 시그널 */}
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-gray-200 dark:border-gray-800" />
          </div>
          <div className="relative flex justify-center">
            <span className="px-4 bg-gradient-to-b from-white to-gray-50 dark:from-gray-900 dark:to-gray-950 text-sm text-gray-400">
              AI 투자 시그널
            </span>
          </div>
        </div>
      </div>

      {/* 투자 시그널 분석 */}
      <InvestSignal />

      {/* 마켓 분석 페이지 링크 */}
      <div className="max-w-5xl mx-auto px-4 mt-4 text-center flex items-center justify-center gap-3">
        <Link
          href="/market"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-green-600 to-emerald-600 text-white text-sm font-semibold hover:shadow-lg transition-all hover:scale-105"
        >
          AI 시장 분석 + 차트 보기
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </Link>
        <Link
          href="/bookmarks"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 text-white text-sm font-semibold hover:shadow-lg transition-all hover:scale-105"
        >
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" /></svg>
          저장한 뉴스
        </Link>
      </div>

      {/* 구분선 - 전체 뉴스 */}
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
