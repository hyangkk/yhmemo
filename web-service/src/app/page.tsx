import Link from "next/link";
import { ROOMS } from "@/lib/rooms";
import type { StrategyRoom } from "@/lib/rooms";
import RecentSessions from "@/components/studio/RecentSessions";

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* Hero */}
      <header className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-violet-600/8 via-transparent to-blue-600/8 dark:from-violet-600/5 dark:to-blue-600/5" />
        <div className="relative max-w-5xl mx-auto px-4 py-16 sm:py-24">
          <div className="text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-sm font-medium mb-6">
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              AI 에이전트 24시간 운영 중
            </div>

            <h1 className="text-4xl sm:text-6xl font-extrabold text-gray-900 dark:text-white tracking-tight">
              AI{" "}
              <span className="bg-gradient-to-r from-violet-500 to-blue-600 bg-clip-text text-transparent">
                전략실
              </span>
            </h1>

            <p className="mt-4 text-lg sm:text-xl text-gray-600 dark:text-gray-300 max-w-2xl mx-auto leading-relaxed">
              각 분야 전문 AI 에이전트가 24시간 정보를 수집·분석하고
              <br className="hidden sm:block" />
              데이터 기반 전략 인사이트를 제공합니다
            </p>
          </div>
        </div>
      </header>

      {/* Strategy Rooms Grid */}
      <section className="max-w-5xl mx-auto px-4 pb-20">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {ROOMS.map((room) => (
            <RoomCard key={room.id} room={room} />
          ))}
        </div>
      </section>

      {/* 최근 촬영 */}
      <RecentSessions />

      {/* Footer */}
      <footer className="max-w-5xl mx-auto px-4 py-12 text-center text-sm text-gray-400 dark:text-gray-500">
        <p>Powered by AI Agents — 자율운영 에이전트 시스템이 24시간 운영합니다.</p>
        <p className="mt-1">© 2026 AI 전략실. Built with Next.js + Supabase.</p>
      </footer>
    </main>
  );
}

function RoomCard({ room }: { room: StrategyRoom }) {
  const isActive = room.status === "active";

  const content = (
    <div
      className={`relative rounded-2xl border p-6 transition-all h-full flex flex-col ${
        isActive
          ? "border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 hover:shadow-xl hover:shadow-violet-500/5 hover:border-violet-300 dark:hover:border-violet-700 cursor-pointer"
          : "border-gray-200/60 dark:border-gray-800/60 bg-gray-50/50 dark:bg-gray-900/50 opacity-70"
      }`}
    >
      {/* Status badge */}
      {!isActive && (
        <div className="absolute top-4 right-4 px-2 py-0.5 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 text-xs font-medium">
          Coming Soon
        </div>
      )}
      {isActive && (
        <div className="absolute top-4 right-4 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          운영 중
        </div>
      )}

      {/* Icon */}
      <div
        className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${room.gradient} flex items-center justify-center text-2xl mb-4 shadow-lg`}
      >
        {room.icon}
      </div>

      {/* Title */}
      <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
        {room.name}
      </h2>
      <p className="text-xs text-gray-400 dark:text-gray-500 font-medium mb-3">
        {room.subtitle}
      </p>

      {/* Description */}
      <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed flex-1">
        {room.description}
      </p>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
        {room.features.map((f) => (
          <span
            key={f}
            className="px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 text-xs text-gray-600 dark:text-gray-400 font-medium"
          >
            {f}
          </span>
        ))}
      </div>

      {/* CTA */}
      {isActive && (
        <div className="mt-4 flex items-center gap-1.5 text-sm font-semibold text-violet-600 dark:text-violet-400">
          전략실 입장
          <svg className="w-4 h-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </div>
      )}
    </div>
  );

  if (isActive) {
    return (
      <Link href={room.path} className="group block">
        {content}
      </Link>
    );
  }

  return content;
}
