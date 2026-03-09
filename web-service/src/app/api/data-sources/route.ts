import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";

export const revalidate = 300; // 5분 캐시

interface SourceStat {
  source: string;
  count: number;
  latest: string | null;
}

export async function GET() {
  try {
    const supabase = getServiceSupabase();

    // 소스별 수집 통계
    const { data: allItems, error } = await supabase
      .from("collected_items")
      .select("source, collected_at")
      .order("collected_at", { ascending: false });

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // 소스별 집계
    const statsMap = new Map<string, { count: number; latest: string | null }>();
    for (const item of allItems || []) {
      const src = item.source || "unknown";
      const existing = statsMap.get(src);
      if (existing) {
        existing.count++;
      } else {
        statsMap.set(src, { count: 1, latest: item.collected_at });
      }
    }

    const sourceStats: SourceStat[] = Array.from(statsMap.entries())
      .map(([source, { count, latest }]) => ({ source, count, latest }))
      .sort((a, b) => b.count - a.count);

    // 최근 24시간 수집 건수
    const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const recentCount = (allItems || []).filter(
      (item) => item.collected_at && item.collected_at > oneDayAgo
    ).length;

    // 큐레이션 통계
    const { count: curatedCount } = await supabase
      .from("curated_items")
      .select("*", { count: "exact", head: true });

    return NextResponse.json({
      sources: sourceStats,
      totalCollected: allItems?.length || 0,
      recentCount24h: recentCount,
      curatedCount: curatedCount || 0,
      updated_at: new Date().toISOString(),
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
