import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.min(Number(searchParams.get("limit") || "20"), 50);
  const offset = Number(searchParams.get("offset") || "0");

  const supabase = getServiceSupabase();

  // 수집된 뉴스 (collected_items)
  const { data: collected, error: collectedError } = await supabase
    .from("collected_items")
    .select("*")
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (collectedError) {
    return NextResponse.json(
      { error: collectedError.message },
      { status: 500 }
    );
  }

  // AI 선별된 뉴스 (curated_items)
  const { data: curated, error: curatedError } = await supabase
    .from("curated_items")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(10);

  return NextResponse.json({
    collected: collected || [],
    curated: curated || [],
    total: collected?.length || 0,
    updated_at: new Date().toISOString(),
  });
}
