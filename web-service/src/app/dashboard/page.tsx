import Link from "next/link";
import { getDashboardData } from "@/lib/dashboard-data";
import type { DashboardData } from "@/lib/dashboard-data";

export const dynamic = "force-dynamic";

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; label: string; pulse: boolean }> = {
    running: { color: "bg-green-500", label: "운영 중", pulse: true },
    success: { color: "bg-green-500", label: "성공", pulse: false },
    completed: { color: "bg-green-500", label: "완료", pulse: false },
    unknown: { color: "bg-gray-400", label: "확인 불가", pulse: false },
    failure: { color: "bg-red-500", label: "실패", pulse: false },
    error: { color: "bg-red-500", label: "에러", pulse: true },
    stopped: { color: "bg-red-400", label: "중지", pulse: false },
    in_progress: { color: "bg-blue-500", label: "실행 중", pulse: true },
    queued: { color: "bg-yellow-500", label: "대기", pulse: true },
    no_data: { color: "bg-gray-300", label: "데이터 없음", pulse: false },
  };
  const s = map[status] || { color: "bg-gray-400", label: status, pulse: false };
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={`w-2 h-2 rounded-full ${s.color} ${s.pulse ? "animate-pulse" : ""}`} />
      {s.label}
    </span>
  );
}

function TimeAgo({ date }: { date: string }) {
  const diff = Date.now() - new Date(date).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return <span>방금 전</span>;
  if (mins < 60) return <span>{mins}분 전</span>;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return <span>{hours}시간 전</span>;
  const days = Math.floor(hours / 24);
  if (days < 7) return <span>{days}일 전</span>;
  return <span>{new Date(date).toLocaleDateString("ko-KR", { month: "short", day: "numeric" })}</span>;
}

export default async function DashboardPage() {
  let data: DashboardData;
  try {
    data = await getDashboardData();
  } catch (err) {
    return (
      <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-2">대시보드 로딩 실패</h1>
          <p className="text-gray-400">{String(err)}</p>
        </div>
      </main>
    );
  }

  const { services, slackAgents, ghAgents, recentActions, recentCommits, summary } = data;

  // 에이전트 그룹별 분류
  const agentGroups: Record<string, typeof slackAgents> = {};
  for (const agent of slackAgents) {
    if (!agentGroups[agent.group]) agentGroups[agent.group] = [];
    agentGroups[agent.group].push(agent);
  }

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      {/* 헤더 */}
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-gray-400 hover:text-white text-sm">
              YH Hub
            </Link>
            <span className="text-gray-600">/</span>
            <h1 className="text-lg font-bold">프로젝트 관리 대시보드</h1>
          </div>
          <div className="flex items-center gap-4 text-sm text-gray-400">
            <span>업데이트: <TimeAgo date={data.updatedAt} /></span>
            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${summary.orchestratorOnline ? "bg-green-900/40 text-green-400" : "bg-red-900/40 text-red-400"}`}>
              <span className={`w-2 h-2 rounded-full ${summary.orchestratorOnline ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
              {summary.orchestratorOnline ? "시스템 정상" : "시스템 이상"}
            </span>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-8 space-y-8">
        {/* 요약 카드 */}
        <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <SummaryCard label="서비스" value={summary.totalServices} sub="플랫폼" />
          <SummaryCard label="슬랙 에이전트" value={summary.totalSlackAgents} sub="오케스트레이터 산하" />
          <SummaryCard label="워크플로우 에이전트" value={summary.totalGhAgents} sub="GitHub Actions" />
          <SummaryCard label="24시간 태스크" value={summary.tasks24h} sub="에이전트 작업" />
        </section>

        {/* 서비스 현황 */}
        <section>
          <SectionHeader title="서비스 현황" description="배포된 서비스 및 프로젝트" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {services.map((svc) => (
              <div key={svc.id} className="rounded-xl border border-gray-800 bg-gray-900/50 p-5 hover:border-gray-700 transition-colors">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-semibold text-white">{svc.name}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{svc.platform} — {svc.region}</p>
                  </div>
                  <StatusBadge status={svc.status} />
                </div>
                <p className="text-sm text-gray-400 mb-3">{svc.description}</p>
                {svc.health && (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(svc.health).map(([k, v]) => (
                      <span key={k} className="px-2 py-0.5 rounded bg-gray-800 text-xs text-gray-300">
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-2">
                  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider ${
                    svc.category === "orchestrator" ? "bg-violet-900/40 text-violet-400" :
                    svc.category === "service" ? "bg-blue-900/40 text-blue-400" :
                    "bg-amber-900/40 text-amber-400"
                  }`}>
                    {svc.category}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 오케스트레이터 에이전트 (그룹별) */}
        <section>
          <SectionHeader
            title="오케스트레이터 에이전트"
            description={`슬랙 에이전트 시스템 산하 ${slackAgents.length}개 에이전트`}
          />
          <div className="space-y-6">
            {Object.entries(agentGroups).map(([group, agents]) => (
              <div key={group}>
                <h3 className="text-sm font-semibold text-gray-400 mb-3 uppercase tracking-wider">{group}</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {agents.map((agent) => (
                    <div key={agent.id} className="rounded-lg border border-gray-800 bg-gray-900/30 p-4 hover:border-gray-700 transition-colors">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{agent.icon}</span>
                          <span className="font-medium text-sm text-white">{agent.name}</span>
                        </div>
                        <StatusBadge status={agent.status} />
                      </div>
                      <div className="flex gap-3 text-xs text-gray-500">
                        <span>태스크: {agent.tasks_24h.total}</span>
                        {agent.tasks_24h.completed > 0 && (
                          <span className="text-green-500">완료: {agent.tasks_24h.completed}</span>
                        )}
                        {agent.tasks_24h.failed > 0 && (
                          <span className="text-red-500">실패: {agent.tasks_24h.failed}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* GitHub Actions 워크플로우 에이전트 */}
        <section>
          <SectionHeader
            title="GitHub Actions 워크플로우 에이전트"
            description={`스케줄/수동 실행 에이전트 ${ghAgents.length}개`}
          />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {ghAgents.map((agent) => (
              <div key={agent.id} className="rounded-lg border border-gray-800 bg-gray-900/30 p-4 hover:border-gray-700 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm text-white">{agent.name}</span>
                  <StatusBadge status={agent.status} />
                </div>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span>스케줄: {agent.schedule}</span>
                  <span className="text-gray-600">|</span>
                  <span>{agent.group}</span>
                </div>
                {agent.lastRun && (
                  <div className="mt-2 text-xs text-gray-500">
                    마지막 실행: <TimeAgo date={agent.lastRun.created_at} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* 최근 활동 2열 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <section>
            <SectionHeader title="최근 GitHub Actions" description="배포 및 워크플로우 실행 기록" />
            <div className="rounded-xl border border-gray-800 bg-gray-900/30 divide-y divide-gray-800">
              {recentActions.length === 0 ? (
                <div className="p-4 text-sm text-gray-500">데이터 없음</div>
              ) : (
                recentActions.map((action) => (
                  <div key={action.id} className="px-4 py-3 flex items-center justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white truncate">{action.name}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {action.head_branch} — <TimeAgo date={action.created_at} />
                      </p>
                    </div>
                    <StatusBadge status={action.conclusion || action.status} />
                  </div>
                ))
              )}
            </div>
          </section>

          <section>
            <SectionHeader title="최근 커밋" description="main 브랜치 코드 변경 이력" />
            <div className="rounded-xl border border-gray-800 bg-gray-900/30 divide-y divide-gray-800">
              {recentCommits.length === 0 ? (
                <div className="p-4 text-sm text-gray-500">데이터 없음</div>
              ) : (
                recentCommits.map((commit) => (
                  <div key={commit.sha} className="px-4 py-3">
                    <div className="flex items-center gap-2 mb-1">
                      <code className="px-1.5 py-0.5 rounded bg-gray-800 text-xs text-violet-400 font-mono">
                        {commit.sha}
                      </code>
                      <span className="text-xs text-gray-500">
                        <TimeAgo date={commit.date} />
                      </span>
                    </div>
                    <p className="text-sm text-gray-300 truncate">{commit.message}</p>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        {/* 아키텍처 요약 */}
        <section>
          <SectionHeader title="시스템 아키텍처" description="전체 프로젝트 구성도" />
          <div className="rounded-xl border border-gray-800 bg-gray-900/30 p-6">
            <pre className="text-xs text-gray-400 font-mono leading-relaxed overflow-x-auto whitespace-pre">{`
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub (hyangkk/yhmemo)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Workflows │  │ Actions  │  │ Secrets  │  │ Branch Protect│   │
│  │ (20개)    │  │ Runners  │  │ Vault    │  │ main → PR only│   │
│  └─────┬────┘  └────┬─────┘  └──────────┘  └──────────────┘   │
│        │ push        │ trigger                                   │
├────────┼────────────┼───────────────────────────────────────────┤
│        ▼            ▼                                            │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │  Fly.io (도쿄 NRT)  │    │  Vercel (서울 ICN1) │            │
│  │  ┌───────────────┐  │    │  ┌───────────────┐  │            │
│  │  │ Orchestrator  │  │    │  │  Next.js 16   │  │            │
│  │  │ ┌───────────┐ │  │    │  │  28 API 라우트 │  │            │
│  │  │ │19 Agents  │ │  │    │  │  투자/스튜디오 │  │            │
│  │  │ └───────────┘ │  │    │  └───────────────┘  │            │
│  │  │ Studio API    │  │    │                      │            │
│  │  └───────────────┘  │    └──────────┬───────────┘            │
│  └──────────┬──────────┘               │                        │
│             │                          │                        │
│             ▼                          ▼                        │
│  ┌──────────────────────────────────────────────┐              │
│  │             Supabase (PostgreSQL)             │              │
│  │  secrets_vault │ agent_tasks │ cost_tracking  │              │
│  │  collected_items │ curated_items │ agent_hr   │              │
│  └──────────────────────────────────────────────┘              │
│                                                                  │
│  ┌───────────────┐  ┌──────────────────┐                       │
│  │ KR Proxy      │  │ BabyMind OS      │                       │
│  │ Fly.io (ICN)  │  │ Docker (로컬)    │                       │
│  └───────────────┘  └──────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
            `}</pre>
          </div>
        </section>
      </div>

      {/* 푸터 */}
      <footer className="border-t border-gray-800 mt-12">
        <div className="max-w-7xl mx-auto px-4 py-6 text-center text-xs text-gray-500">
          <p>프로젝트 관리 대시보드 — 운영 현황을 실시간으로 모니터링합니다.</p>
        </div>
      </footer>
    </main>
  );
}

function SummaryCard({ label, value, sub }: { label: string; value: number; sub: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
      <p className="text-2xl font-bold text-white">{value}</p>
      <p className="text-sm font-medium text-gray-300 mt-1">{label}</p>
      <p className="text-xs text-gray-500">{sub}</p>
    </div>
  );
}

function SectionHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-xl font-bold text-white">{title}</h2>
      <p className="text-sm text-gray-400">{description}</p>
    </div>
  );
}
