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

const PROJECT_HISTORY = [
  {
    id: "multicam-studio",
    icon: "🎬",
    title: "멀티캠 스튜디오",
    period: "03-11 ~",
    status: "active" as const,
    description: "다중 카메라 동시 촬영 + AI 자동 교차편집. BGM, 자막(Groq), AI 감독 모드, 프롬프트 편집 지원",
    features: ["멀티캠 촬영", "AI 교차편집", "BGM (Pixabay)", "자동 자막", "감독 모드"],
  },
  {
    id: "auto-trading",
    icon: "📈",
    title: "AI 자동매매 시스템",
    period: "03-06 ~",
    status: "active" as const,
    description: "LS증권 모의투자 연동, AutoTrader + SwingTrader 24시간 자동 모니터링/거래, 매매일지 학습",
    features: ["LS증권 연동", "자동매매", "스윙트레이딩", "매매일지 학습", "포트폴리오 관리"],
  },
  {
    id: "invest-platform",
    icon: "📊",
    title: "AI 투자전략실",
    period: "03-06 ~",
    status: "active" as const,
    description: "실시간 시세조회, 소셜 센티멘트 분석, 투자 리서치/리포트, 유전 알고리즘 전략 진화",
    features: ["실시간 시세", "센티멘트 분석", "투자 리서치", "유전 알고리즘", "백테스트"],
  },
  {
    id: "bulletin-scraper",
    icon: "📢",
    title: "게시판 크롤링 시스템",
    period: "03-13 ~",
    status: "active" as const,
    description: "지자체 게시판(용인시 고시공고/문화행사 등) 자동 크롤링 → 새 글 노션 저장, Playwright iframe 지원",
    features: ["지자체 게시판", "자동 크롤링", "노션 저장", "Playwright"],
  },
  {
    id: "blog-scraper",
    icon: "🌏",
    title: "네이버 블로그 크롤링",
    period: "03-13 ~",
    status: "active" as const,
    description: "네이버 블로그 본문/이미지 추출 → 노션 저장. Playwright 자동 폴백, 동영상/지도/링크 임베드 추출",
    features: ["블로그 크롤링", "노션 저장", "이미지 추출", "Playwright 폴백"],
  },
  {
    id: "diary-system",
    icon: "📓",
    title: "생각일기 + 이사회 시스템",
    period: "03-03 ~",
    status: "active" as const,
    description: "노션 생각일기 연동. AI 이사회 분석/표결, 매일 밤 10시 분석알림, 장기 트렌드 분석, 슬랙 명언 한마디",
    features: ["노션 연동", "AI 이사회", "분석알림", "장기 트렌드", "명언 한마디"],
  },
  {
    id: "slack-agents",
    icon: "🤖",
    title: "24시간 자율 에이전트 시스템",
    period: "03-05 ~",
    status: "active" as const,
    description: "슬랙 기반 19개 에이전트 24시간 운영. 자연어 명령, 자율 제안, 동적 에이전트 생성/해고, HR 평가",
    features: ["자연어 명령", "자율 운영", "동적 생성/해고", "HR 평가", "Fly.io 배포"],
  },
  {
    id: "news-collection",
    icon: "📰",
    title: "뉴스 자동 수집 + 큐레이션",
    period: "02-19 ~",
    status: "active" as const,
    description: "Google News 기반 뉴스 수집 → AI 큐레이션 → 슬랙 전달. K-Startup 공고 자동 수집 포함",
    features: ["뉴스 수집", "AI 큐레이션", "K-Startup", "키워드 필터"],
  },
  {
    id: "youtube-summary",
    icon: "🎥",
    title: "YouTube 트랜스크립트 요약",
    period: "03-09",
    status: "active" as const,
    description: "YouTube 영상 자막 추출 + AI 요약. Innertube API, 수동 자막 입력 폴백",
    features: ["자막 추출", "AI 요약", "Innertube API"],
  },
  {
    id: "interview-agent",
    icon: "🎙️",
    title: "인터뷰/대본 생성 에이전트",
    period: "03-03 ~ 03-05",
    status: "paused" as const,
    description: "텔레그램 Q&A → 노션 정리 → 유튜브 대본 자동 생성",
    features: ["Q&A 인터뷰", "노션 정리", "대본 생성"],
  },
  {
    id: "fortune-agent",
    icon: "🔮",
    title: "오늘의 운세 에이전트",
    period: "03-08",
    status: "paused" as const,
    description: "하루 3회 AI 운세 자동 전송 (운영 중단됨)",
    features: ["AI 운세", "자동 전송"],
  },
  {
    id: "babymind-os",
    icon: "👶",
    title: "BabyMind OS",
    period: "03-11",
    status: "prototype" as const,
    description: "육아 AI CCTV 모니터링 + MCP 서버 (프로토타입)",
    features: ["CCTV 모니터링", "MCP 서버", "Docker"],
  },
];

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

  // 슬랙 에이전트: 24시간 내 태스크 있는 것 = 활성
  const activeSlack = slackAgents
    .filter((a) => a.tasks_24h.total > 0)
    .sort((a, b) => b.tasks_24h.total - a.tasks_24h.total);
  const dormantSlack = slackAgents.filter((a) => a.tasks_24h.total === 0);

  // GH 에이전트: lastRun 있는 것 = 활성, 최근 순 정렬
  const activeGh = ghAgents
    .filter((a) => a.lastRun)
    .sort((a, b) => new Date(b.lastRun!.created_at).getTime() - new Date(a.lastRun!.created_at).getTime());
  const dormantGh = ghAgents.filter((a) => !a.lastRun);

  // 서비스: running 상위
  const activeServices = services.filter((s) => s.status === "running");
  const otherServices = services.filter((s) => s.status !== "running");

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
          <SummaryCard label="서비스" value={activeServices.length} sub={`${services.length}개 중 운영 중`} highlight />
          <SummaryCard label="활성 에이전트" value={activeSlack.length + activeGh.length} sub={`${slackAgents.length + ghAgents.length}개 중 최근 활동`} highlight />
          <SummaryCard label="24시간 태스크" value={summary.tasks24h} sub="에이전트 작업" />
          <SummaryCard label="비활성" value={dormantSlack.length + dormantGh.length} sub="최근 활동 없음" />
        </section>

        {/* 운영 중 서비스 */}
        <section>
          <SectionHeader title="운영 중 서비스" description={`${activeServices.length}개 서비스 가동 중`} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {activeServices.map((svc) => (
              <div key={svc.id} className="rounded-xl border border-gray-800 bg-gray-900/50 p-5 hover:border-gray-700 transition-colors">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h3 className="font-semibold text-white">{svc.name}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{svc.platform} — {svc.region}</p>
                  </div>
                  <StatusBadge status={svc.status} />
                </div>
                <p className="text-sm text-gray-400">{svc.description}</p>
                {svc.health && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {Object.entries(svc.health).map(([k, v]) => (
                      <span key={k} className="px-2 py-0.5 rounded bg-gray-800 text-xs text-gray-300">
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* 활성 에이전트 (24시간 내 태스크 있음) */}
        {activeSlack.length > 0 && (
          <section>
            <SectionHeader
              title="활성 에이전트"
              description={`최근 24시간 내 ${summary.tasks24h}건 작업 수행`}
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {activeSlack.map((agent) => (
                <div key={agent.id} className="rounded-lg border border-gray-700 bg-gray-900/60 p-4 hover:border-gray-600 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{agent.icon}</span>
                      <span className="font-medium text-sm text-white">{agent.name}</span>
                    </div>
                    <StatusBadge status={agent.status} />
                  </div>
                  <div className="flex gap-3 text-xs">
                    <span className="text-gray-400">태스크: <span className="text-white font-semibold">{agent.tasks_24h.total}</span></span>
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
          </section>
        )}

        {/* 최근 실행 워크플로우 */}
        {activeGh.length > 0 && (
          <section>
            <SectionHeader
              title="최근 실행 워크플로우"
              description={`${activeGh.length}개 워크플로우 실행 기록 있음`}
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {activeGh.map((agent) => (
                <div key={agent.id} className="rounded-lg border border-gray-700 bg-gray-900/60 p-4 hover:border-gray-600 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-sm text-white">{agent.name}</span>
                    <StatusBadge status={agent.status} />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500">
                    <span>{agent.group}</span>
                    <span className="text-gray-600">|</span>
                    <span>스케줄: {agent.schedule}</span>
                  </div>
                  {agent.lastRun && (
                    <div className="mt-2 text-xs text-gray-400">
                      마지막 실행: <TimeAgo date={agent.lastRun.created_at} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 최근 활동 (Actions + Commits) 2열 */}
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

        {/* 비활성 항목 (접이식) */}
        {(dormantSlack.length > 0 || dormantGh.length > 0 || otherServices.length > 0) && (
          <details className="group">
            <summary className="cursor-pointer select-none flex items-center gap-2 text-gray-500 hover:text-gray-300 transition-colors py-2">
              <svg className="w-4 h-4 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              <span className="text-sm font-medium">
                비활성 항목 ({dormantSlack.length + dormantGh.length + otherServices.length}개)
              </span>
              <span className="text-xs text-gray-600">최근 24시간 활동 없음</span>
            </summary>

            <div className="mt-4 space-y-6">
              {/* 비활성 서비스 */}
              {otherServices.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-500 mb-3">서비스</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {otherServices.map((svc) => (
                      <div key={svc.id} className="rounded-lg border border-gray-800/60 bg-gray-900/20 p-4 opacity-60">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="text-sm text-gray-400">{svc.name}</span>
                            <p className="text-xs text-gray-600">{svc.platform}</p>
                          </div>
                          <StatusBadge status={svc.status} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 비활성 슬랙 에이전트 */}
              {dormantSlack.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-500 mb-3">슬랙 에이전트 (활동 없음)</h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {dormantSlack.map((agent) => (
                      <div key={agent.id} className="rounded-lg border border-gray-800/50 bg-gray-900/20 px-3 py-2.5 opacity-50">
                        <div className="flex items-center gap-2">
                          <span className="text-sm">{agent.icon}</span>
                          <span className="text-xs text-gray-500 truncate">{agent.name}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 비활성 GH 워크플로우 */}
              {dormantGh.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-500 mb-3">워크플로우 (실행 기록 없음)</h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {dormantGh.map((agent) => (
                      <div key={agent.id} className="rounded-lg border border-gray-800/50 bg-gray-900/20 px-3 py-2.5 opacity-50">
                        <span className="text-xs text-gray-500">{agent.name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}
        {/* 주요 구축 내역 */}
        <section>
          <SectionHeader title="주요 구축 내역" description="2026-02-19 ~ 현재 | 요청 → 구축한 주요 기능 타임라인" />
          <div className="space-y-3">
            {PROJECT_HISTORY.map((item) => (
              <div key={item.id} className="rounded-xl border border-gray-800 bg-gray-900/40 p-4 hover:border-gray-700 transition-colors">
                <div className="flex items-start gap-4">
                  <div className="shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-gray-700 to-gray-800 flex items-center justify-center text-lg">
                    {item.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-semibold text-white">{item.title}</h3>
                      <span className="px-1.5 py-0.5 rounded bg-gray-800 text-[10px] text-gray-500 font-mono">{item.period}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        item.status === "active" ? "bg-green-900/40 text-green-400" :
                        item.status === "paused" ? "bg-yellow-900/40 text-yellow-400" :
                        "bg-gray-800 text-gray-500"
                      }`}>
                        {item.status === "active" ? "운영 중" : item.status === "paused" ? "일시중단" : "프로토타입"}
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 mt-1">{item.description}</p>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {item.features.map((f) => (
                        <span key={f} className="px-1.5 py-0.5 rounded bg-gray-800/80 text-[10px] text-gray-400">{f}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ))}
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

function SummaryCard({ label, value, sub, highlight }: { label: string; value: number; sub: string; highlight?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${highlight ? "border-gray-700 bg-gray-900/70" : "border-gray-800 bg-gray-900/50"}`}>
      <p className={`text-2xl font-bold ${highlight ? "text-white" : "text-gray-300"}`}>{value}</p>
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
