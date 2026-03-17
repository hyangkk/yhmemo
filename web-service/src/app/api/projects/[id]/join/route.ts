import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 프로젝트 참여
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();
  const { name, userId, deviceId } = await req.json();

  // 프로젝트 존재 확인
  const { data: project } = await supabase
    .from('projects')
    .select('id')
    .eq('id', id)
    .single();

  if (!project) {
    return NextResponse.json({ error: '프로젝트를 찾을 수 없습니다' }, { status: 404 });
  }

  // 이미 멤버인지 확인
  if (userId) {
    const { data: existing } = await supabase
      .from('project_members')
      .select('id')
      .eq('project_id', id)
      .eq('user_id', userId)
      .single();

    if (existing) {
      return NextResponse.json(existing);
    }
  }

  const { data: member, error } = await supabase
    .from('project_members')
    .insert({
      project_id: id,
      user_id: userId || null,
      name: name || '참여자',
      role: 'member',
      device_id: deviceId || null,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(member);
}
