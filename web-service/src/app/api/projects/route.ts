import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { generateProjectCode } from '@/lib/project';

// GET: 내 프로젝트 목록
export async function GET(req: NextRequest) {
  const supabase = getServiceSupabase();

  // Authorization 헤더에서 유저 확인
  const token = req.headers.get('authorization')?.replace('Bearer ', '');
  if (!token) {
    return NextResponse.json({ error: '로그인이 필요합니다' }, { status: 401 });
  }

  const { data: { user }, error: authError } = await supabase.auth.getUser(token);
  if (authError || !user) {
    return NextResponse.json({ error: '인증 실패' }, { status: 401 });
  }

  // 내가 멤버인 프로젝트 + 내가 만든 프로젝트
  const { data: memberProjects } = await supabase
    .from('project_members')
    .select('project_id')
    .eq('user_id', user.id);

  const projectIds = memberProjects?.map(m => m.project_id) || [];

  let query = supabase
    .from('projects')
    .select(`
      *,
      project_clips(id),
      project_members(id, name, role),
      project_results(id, status, duration_ms, created_at)
    `);

  // projectIds가 비어있으면 owner_id만으로 필터 (빈 in.()은 PostgREST 에러)
  if (projectIds.length > 0) {
    query = query.or(`owner_id.eq.${user.id},id.in.(${projectIds.join(',')})`);
  } else {
    query = query.eq('owner_id', user.id);
  }

  const { data: projects } = await query.order('updated_at', { ascending: false });

  return NextResponse.json(projects || []);
}

// POST: 프로젝트 생성
export async function POST(req: NextRequest) {
  const supabase = getServiceSupabase();

  const token = req.headers.get('authorization')?.replace('Bearer ', '');
  if (!token) {
    return NextResponse.json({ error: '로그인이 필요합니다' }, { status: 401 });
  }

  const { data: { user }, error: authError } = await supabase.auth.getUser(token);
  if (authError || !user) {
    return NextResponse.json({ error: '인증 실패' }, { status: 401 });
  }

  const { title, description } = await req.json();

  // 고유 코드 생성 (충돌 시 재시도)
  let code = '';
  for (let i = 0; i < 10; i++) {
    code = generateProjectCode();
    const { data: existing } = await supabase
      .from('projects')
      .select('id')
      .eq('code', code)
      .single();
    if (!existing) break;
  }

  const { data: project, error } = await supabase
    .from('projects')
    .insert({
      owner_id: user.id,
      code,
      title: title || '새 프로젝트',
      description: description || null,
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // 오너를 멤버로 자동 추가
  const { data: profile } = await supabase
    .from('profiles')
    .select('name')
    .eq('id', user.id)
    .single();

  await supabase.from('project_members').insert({
    project_id: project.id,
    user_id: user.id,
    name: profile?.name || '호스트',
    role: 'owner',
  });

  return NextResponse.json(project);
}
