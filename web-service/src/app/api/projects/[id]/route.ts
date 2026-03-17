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

  return NextResponse.json({
    project,
    members: members.data || [],
    clips: clips.data || [],
    results: results.data || [],
  });
}
