import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 편집 요청 (타임라인 기반)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const supabase = getServiceSupabase();
  const { mode, audio_mode, prompt } = await req.json();

  // 클립 존재 확인
  const { data: clips } = await supabase
    .from('project_clips')
    .select('id')
    .eq('project_id', projectId);

  if (!clips || clips.length === 0) {
    return NextResponse.json({ error: '클립이 없습니다' }, { status: 400 });
  }

  // result 생성 - storage_path에 모드 인코딩 (기존 studio 방식과 호환)
  const storagePath = mode === 'prompt'
    ? `mode:prompt:${prompt}${audio_mode === 'best' ? ':audio=best' : ''}`
    : `mode:${mode || 'timeline'}${audio_mode === 'best' ? ':audio=best' : ''}`;

  const { data: result, error } = await supabase
    .from('project_results')
    .insert({
      project_id: projectId,
      storage_path: storagePath,
      status: 'processing',
      edit_mode: mode || 'timeline',
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // 프로젝트를 editing 상태로 (폴링 루프가 감지)
  await supabase
    .from('projects')
    .update({ status: 'editing', updated_at: new Date().toISOString() })
    .eq('id', projectId);

  return NextResponse.json({ ok: true, result });
}
