import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// GET: 프로젝트 상세 (멤버, 클립, 결과 포함)
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();

  const { data: project, error } = await supabase
    .from('projects')
    .select('*')
    .eq('id', id)
    .single();

  if (error || !project) {
    return NextResponse.json({ error: '프로젝트를 찾을 수 없습니다' }, { status: 404 });
  }

  const [members, clips, results] = await Promise.all([
    supabase.from('project_members').select('*').eq('project_id', id).order('created_at'),
    supabase.from('project_clips').select('*').eq('project_id', id).order('started_at'),
    supabase.from('project_results').select('*').eq('project_id', id).order('created_at', { ascending: false }),
  ]);

  // 30분 이상 processing 상태인 결과를 error로 자동 전환
  const staleThreshold = new Date(Date.now() - 30 * 60 * 1000).toISOString();
  const resultList = results.data || [];
  const staleResults = resultList.filter(
    (r: { status: string; created_at: string }) => r.status === 'processing' && r.created_at < staleThreshold
  );
  if (staleResults.length > 0) {
    await supabase
      .from('project_results')
      .update({ status: 'error' })
      .in('id', staleResults.map((r: { id: string }) => r.id));
    // 상태 반영
    staleResults.forEach((r: { status: string }) => { r.status = 'error'; });
  }

  return NextResponse.json({
    project,
    members: members.data || [],
    clips: clips.data || [],
    results: resultList,
  });
}
