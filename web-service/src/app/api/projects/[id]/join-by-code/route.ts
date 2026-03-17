import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 프로젝트 코드로 검색 후 멤버 참여
// [id] 파라미터에 프로젝트 코드(6자리)가 들어옴
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: code } = await params;
  const supabase = getServiceSupabase();
  const { userId, name } = await req.json();

  // 코드로 프로젝트 찾기
  const { data: project } = await supabase
    .from('projects')
    .select('id')
    .eq('code', code.toUpperCase())
    .single();

  if (!project) {
    return NextResponse.json({ error: '프로젝트를 찾을 수 없습니다' }, { status: 404 });
  }

  // 이미 멤버인지 확인
  if (userId) {
    const { data: existing } = await supabase
      .from('project_members')
      .select('id')
      .eq('project_id', project.id)
      .eq('user_id', userId)
      .single();

    if (existing) {
      return NextResponse.json({ projectId: project.id });
    }
  }

  // 멤버로 추가
  const { error } = await supabase
    .from('project_members')
    .insert({
      project_id: project.id,
      user_id: userId || null,
      name: name || '참여자',
      role: 'member',
    });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ projectId: project.id });
}
