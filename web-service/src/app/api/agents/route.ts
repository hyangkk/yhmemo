import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const supabase = getServiceSupabase();

    // 최근 에이전트 태스크 현황 (최근 24시간)
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

    const { data: tasks } = await supabase
      .from("agent_tasks")
      .select("from_agent, to_agent, task_type, status, created_at, updated_at")
      .gte("created_at", since)
      .order("created_at", { ascending: false })
      .limit(100);

    // 에이전트별 통계 집계
    const agentStats: Record<string, {
      total: number;
      completed: number;
      failed: number;
      in_progress: number;
      last_activity: string;
    }> = {};

    const agentNames = ["collector", "curator", "quote", "proactive", "investment"];

    for (const name of agentNames) {
      agentStats[name] = { total: 0, completed: 0, failed: 0, in_progress: 0, last_activity: "" };
    }

    for (const task of tasks || []) {
      const agent = task.from_agent || task.to_agent;
      if (!agentStats[agent]) {
        agentStats[agent] = { total: 0, completed: 0, failed: 0, in_progress: 0, last_activity: "" };
      }
      agentStats[agent].total++;
      if (task.status === "completed") agentStats[agent].completed++;
      else if (task.status === "failed") agentStats[agent].failed++;
      else if (task.status === "in_progress") agentStats[agent].in_progress++;

      if (!agentStats[agent].last_activity || task.created_at > agentStats[agent].last_activity) {
        agentStats[agent].last_activity = task.updated_at || task.created_at;
      }
    }

    // 수집된 뉴스 수 (24시간)
    const { count: newsCount } = await supabase
      .from("collected_items")
      .select("*", { count: "exact", head: true })
      .gte("created_at", since);

    // 큐레이션된 뉴스 수
    const { count: curatedCount } = await supabase
      .from("curated_items")
      .select("*", { count: "exact", head: true })
      .gte("created_at", since);

    return NextResponse.json({
      agents: agentStats,
      summary: {
        total_tasks_24h: tasks?.length || 0,
        news_collected_24h: newsCount || 0,
        news_curated_24h: curatedCount || 0,
      },
      updated_at: new Date().toISOString(),
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
