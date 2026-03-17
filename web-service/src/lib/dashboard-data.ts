import { getServiceSupabase } from "@/lib/supabase";

// 서비스 정의
const SERVICES = [
  {
    id: "slack-agents",
    name: "슬랙 에이전트 오케스트레이터",
    platform: "Fly.io",
    region: "도쿄 (NRT)",
    description: "24/7 AI 에이전트 시스템 — Slack Socket Mode로 상시 운영",
    healthUrl: "https://yhmbp14.fly.dev/health",
    category: "orchestrator",
  },
  {
    id: "web-service",
    name: "AI 전략실 웹서비스",
    platform: "Vercel",
    region: "서울 (ICN1)",
    description: "Next.js 대시보드 + API (투자, 스튜디오, 유튜브 등)",
    healthUrl: null,
    category: "service",
  },
  {
    id: "babymind-os",
    name: "BabyMind OS",
    platform: "Docker (로컬)",
    region: "N/A",
    description: "육아 AI CCTV 모니터링 + MCP 서버",
    healthUrl: null,
    category: "project",
  },
  {
    id: "kr-proxy",
    name: "한국 프록시 서버",
    platform: "Fly.io",
    region: "서울 (ICN)",
    description: "한국 리전 프록시 (의료진흥원 등 한국 전용 사이트 접근)",
    healthUrl: null,
    category: "service",
  },
];

const SLACK_AGENTS = [
  { id: "collector", name: "뉴스 수집 에이전트", icon: "📰", group: "정보수집" },
  { id: "curator", name: "뉴스 큐레이션 에이전트", icon: "✨", group: "정보수집" },
  { id: "proactive", name: "자율 제안 에이전트", icon: "💡", group: "자율운영" },
  { id: "quote", name: "시세 조회 에이전트", icon: "💹", group: "투자" },
  { id: "invest", name: "투자 분석 에이전트", icon: "📊", group: "투자" },
  { id: "invest_report", name: "투자 리포트 에이전트", icon: "📋", group: "투자" },
  { id: "invest_research", name: "투자 리서치 에이전트", icon: "🔬", group: "투자" },
  { id: "investment", name: "포트폴리오 에이전트", icon: "💰", group: "투자" },
  { id: "auto_trader", name: "자동 트레이딩 에이전트", icon: "🤖", group: "투자" },
  { id: "swing_trader", name: "스윙 트레이딩 에이전트", icon: "📈", group: "투자" },
  { id: "trade_history_analyzer", name: "거래이력 분석 에이전트", icon: "🔍", group: "투자" },
  { id: "market_info", name: "시장 정보 에이전트", icon: "🌐", group: "투자" },
  { id: "sentiment", name: "소셜 센티멘트 에이전트", icon: "💬", group: "분석" },
  { id: "task_board", name: "태스크보드 에이전트", icon: "📌", group: "자율운영" },
  { id: "fortune", name: "운세 에이전트", icon: "🔮", group: "생활" },
  { id: "diary_quote", name: "일기×시세 에이전트", icon: "📓", group: "생활" },
  { id: "diary_daily_alert", name: "일일 알림 에이전트", icon: "🔔", group: "생활" },
  { id: "bulletin", name: "게시판 모니터링 에이전트", icon: "📢", group: "분석" },
  { id: "naver_blog_scraper", name: "네이버 블로그 스크래퍼", icon: "🌏", group: "정보수집" },
];

const GH_WORKFLOW_AGENTS = [
  { id: "news-idea-agent", name: "뉴스 아이디어 에이전트", schedule: "매시간", group: "콘텐츠" },
  { id: "bi-market-agent", name: "BI 시장 인텔리전스", schedule: "수동", group: "분석" },
  { id: "interview-agent", name: "인터뷰 에이전트", schedule: "수동", group: "콘텐츠" },
  { id: "notion-diary-agent", name: "노션 일기 동기화", schedule: "수동", group: "생활" },
  { id: "diary-board-agent", name: "일기 게시판 에이전트", schedule: "수동", group: "생활" },
  { id: "diary-analysis-agent", name: "일기 분석 에이전트", schedule: "수동", group: "분석" },
  { id: "board-chat-agent", name: "게시판 채팅 에이전트", schedule: "수동", group: "분석" },
  { id: "board-agenda-agent", name: "안건 도출 에이전트", schedule: "수동", group: "분석" },
  { id: "kstartup-agent", name: "K스타트업 분석 에이전트", schedule: "수동", group: "분석" },
];

async function checkFlyHealth(url: string): Promise<{ ok: boolean; data?: Record<string, unknown> }> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(5000), cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      return { ok: true, data };
    }
    return { ok: false };
  } catch {
    return { ok: false };
  }
}

async function getRecentGitHubActions(ghToken: string | undefined) {
  if (!ghToken) return [];
  try {
    const res = await fetch(
      "https://api.github.com/repos/hyangkk/yhmemo/actions/runs?per_page=15",
      {
        headers: {
          Authorization: `token ${ghToken}`,
          Accept: "application/vnd.github+json",
        },
        signal: AbortSignal.timeout(8000),
        cache: "no-store",
      }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return (data.workflow_runs || []).map((r: Record<string, unknown>) => ({
      id: r.id,
      name: r.name,
      status: r.status,
      conclusion: r.conclusion,
      created_at: r.created_at,
      updated_at: r.updated_at,
      html_url: r.html_url,
      head_branch: r.head_branch,
    }));
  } catch {
    return [];
  }
}

async function getRecentCommits(ghToken: string | undefined) {
  if (!ghToken) return [];
  try {
    const res = await fetch(
      "https://api.github.com/repos/hyangkk/yhmemo/commits?per_page=10",
      {
        headers: {
          Authorization: `token ${ghToken}`,
          Accept: "application/vnd.github+json",
        },
        signal: AbortSignal.timeout(8000),
        cache: "no-store",
      }
    );
    if (!res.ok) return [];
    const data = await res.json();
    return data.map((c: Record<string, unknown>) => {
      const commit = c.commit as Record<string, unknown>;
      const author = commit.author as Record<string, unknown>;
      return {
        sha: (c.sha as string).slice(0, 7),
        message: (commit.message as string).split("\n")[0],
        date: author.date,
        url: c.html_url,
      };
    });
  } catch {
    return [];
  }
}

export interface DashboardData {
  services: {
    id: string;
    name: string;
    platform: string;
    region: string;
    description: string;
    category: string;
    status: string;
    health: Record<string, unknown> | null;
  }[];
  slackAgents: {
    id: string;
    name: string;
    icon: string;
    group: string;
    status: string;
    tasks_24h: { total: number; completed: number; failed: number };
  }[];
  ghAgents: {
    id: string;
    name: string;
    schedule: string;
    group: string;
    status: string;
    lastRun: {
      name: string;
      status: string;
      conclusion: string | null;
      created_at: string;
      html_url: string;
    } | null;
  }[];
  recentActions: {
    id: number;
    name: string;
    status: string;
    conclusion: string | null;
    created_at: string;
    html_url: string;
    head_branch: string;
  }[];
  recentCommits: {
    sha: string;
    message: string;
    date: string;
    url: string;
  }[];
  summary: {
    totalServices: number;
    totalSlackAgents: number;
    totalGhAgents: number;
    orchestratorOnline: boolean;
    tasks24h: number;
  };
  updatedAt: string;
}

export async function getDashboardData(): Promise<DashboardData> {
  const supabase = getServiceSupabase();

  // GH_TOKEN 조회
  let ghToken: string | undefined;
  try {
    const { data: tokenData } = await supabase
      .from("secrets_vault")
      .select("value")
      .eq("key", "GH_TOKEN")
      .single();
    ghToken = tokenData?.value;
  } catch {
    // GH_TOKEN 없으면 GitHub 관련 데이터 스킵
  }

  // 병렬 데이터 수집
  const [flyHealth, actions, commits] = await Promise.all([
    checkFlyHealth("https://yhmbp14.fly.dev/health"),
    getRecentGitHubActions(ghToken),
    getRecentCommits(ghToken),
  ]);

  // 에이전트 태스크 통계 (24시간)
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  let tasks: Record<string, unknown>[] = [];
  try {
    const { data } = await supabase
      .from("agent_tasks")
      .select("from_agent, to_agent, task_type, status, created_at")
      .gte("created_at", since)
      .order("created_at", { ascending: false })
      .limit(200);
    tasks = data || [];
  } catch {
    // 테이블 없을 수 있음
  }

  // 에이전트별 태스크 집계
  const agentTaskStats: Record<string, { total: number; completed: number; failed: number }> = {};
  for (const task of tasks) {
    const agent = (task.from_agent || task.to_agent) as string;
    if (!agentTaskStats[agent]) {
      agentTaskStats[agent] = { total: 0, completed: 0, failed: 0 };
    }
    agentTaskStats[agent].total++;
    if (task.status === "completed") agentTaskStats[agent].completed++;
    if (task.status === "failed") agentTaskStats[agent].failed++;
  }

  // 서비스 상태 조합
  const services = SERVICES.map((svc) => {
    if (svc.id === "slack-agents") {
      return { ...svc, status: flyHealth.ok ? "running" : "unknown", health: flyHealth.data || null };
    }
    if (svc.id === "web-service") {
      return { ...svc, status: "running" as const, health: null };
    }
    return { ...svc, status: "unknown" as const, health: null };
  });

  // 슬랙 에이전트 상태 조합
  const slackAgents = SLACK_AGENTS.map((agent) => ({
    ...agent,
    status: flyHealth.ok ? "running" : "unknown",
    tasks_24h: agentTaskStats[agent.id] || { total: 0, completed: 0, failed: 0 },
  }));

  // GitHub Actions 워크플로우 상태
  const ghAgents = GH_WORKFLOW_AGENTS.map((agent) => {
    const matchingRun = (actions as Record<string, unknown>[]).find(
      (a) => (a.name as string)?.toLowerCase().includes(agent.id.replace(/-/g, " ").replace("agent", "").trim())
    );
    return {
      ...agent,
      lastRun: matchingRun as DashboardData["ghAgents"][number]["lastRun"] || null,
      status: matchingRun
        ? (matchingRun.conclusion as string) || (matchingRun.status as string)
        : "no_data",
    };
  });

  return {
    services,
    slackAgents,
    ghAgents,
    recentActions: (actions as DashboardData["recentActions"]).slice(0, 10),
    recentCommits: commits as DashboardData["recentCommits"],
    summary: {
      totalServices: SERVICES.length,
      totalSlackAgents: SLACK_AGENTS.length,
      totalGhAgents: GH_WORKFLOW_AGENTS.length,
      orchestratorOnline: flyHealth.ok,
      tasks24h: tasks.length,
    },
    updatedAt: new Date().toISOString(),
  };
}
