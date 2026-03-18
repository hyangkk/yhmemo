import Link from "next/link";

const PROJECTS = [
  {
    id: "dashboard",
    name: "프로젝트 관리 대시보드",
    description: "전체 서비스, 에이전트, 워크플로우 현황을 한눈에 모니터링",
    icon: "📊",
    gradient: "from-gray-700 to-gray-900",
    path: "/dashboard",
    tags: ["모니터링", "상태 관리", "실시간"],
  },
  {
    id: "invest",
    name: "AI 투자전략실",
    description: "실시간 시장 시그널 포착 + 뉴스 크로스 분석 + 투자 전략 제시",
    icon: "📈",
    gradient: "from-amber-500 to-orange-600",
    path: "/invest",
    tags: ["실시간 시그널", "크로스 분석", "24시간 운영"],
  },
  {
    id: "studio",
    name: "SupaCam 슈파캠",
    description: "다중 카메라 영상 촬영 + AI 자동 편집 + 최종 결과물 생성",
    icon: "🎬",
    gradient: "from-violet-500 to-purple-600",
    path: "/studio",
    tags: ["영상 편집", "AI 자동화", "SupaCam"],
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900 flex flex-col">
      {/* Hero */}
      <header className="relative overflow-hidden flex-shrink-0">
        <div className="absolute inset-0 bg-gradient-to-br from-violet-600/8 via-transparent to-blue-600/8 dark:from-violet-600/5 dark:to-blue-600/5" />
        <div className="relative max-w-3xl mx-auto px-4 pt-20 pb-12 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-sm font-medium mb-6">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            AI 에이전트 24시간 운영 중
          </div>

          <h1 className="text-4xl sm:text-5xl font-extrabold text-gray-900 dark:text-white tracking-tight">
            YH{" "}
            <span className="bg-gradient-to-r from-violet-500 to-blue-600 bg-clip-text text-transparent">
              Hub
            </span>
          </h1>

          <p className="mt-3 text-lg text-gray-500 dark:text-gray-400">
            프로젝트 & 에이전트 통합 관리
          </p>
        </div>
      </header>

      {/* Project Cards */}
      <section className="flex-1 max-w-3xl mx-auto px-4 pb-20 w-full">
        <div className="grid grid-cols-1 gap-4">
          {PROJECTS.map((project) => (
            <Link key={project.id} href={project.path} className="group block">
              <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 hover:shadow-xl hover:border-violet-300 dark:hover:border-violet-700 transition-all">
                <div className="flex items-start gap-5">
                  <div
                    className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${project.gradient} flex items-center justify-center text-2xl shadow-lg shrink-0`}
                  >
                    {project.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                        {project.name}
                      </h2>
                      <svg
                        className="w-4 h-4 text-gray-400 transition-transform group-hover:translate-x-1"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                    <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                      {project.description}
                    </p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      {project.tags.map((tag) => (
                        <span
                          key={tag}
                          className="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400 font-medium"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="max-w-3xl mx-auto px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
        <p>&copy; 2026 YH Hub. Built with Next.js + Supabase.</p>
      </footer>
    </main>
  );
}
