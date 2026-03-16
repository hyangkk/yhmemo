import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 특정 모드로 편집 요청 (기존 클립을 재사용)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const { mode, audio_mode, prompt } = await req.json();

  if (!mode || !['auto', 'director', 'split', 'pip', 'prompt'].includes(mode)) {
    return NextResponse.json({ error: '잘못된 편집 모드' }, { status: 400 });
  }

  if (mode === 'prompt' && !prompt) {
    return NextResponse.json({ error: '프롬프트를 입력해주세요' }, { status: 400 });
  }

  const supabase = getServiceSupabase();

  // 클립이 있는지 확인
  const { data: clips } = await supabase
    .from('studio_clips')
    .select('id')
    .eq('session_id', id);

  if (!clips?.length) {
    return NextResponse.json({ error: '클립이 없습니다' }, { status: 400 });
  }

  // 새 result 생성 (storage_path에 모드 정보 저장)
  const { data: result, error } = await supabase
    .from('studio_results')
    .insert({
      session_id: id,
      storage_path: mode === 'prompt'
        ? `mode:prompt:${prompt}${audio_mode === 'best' ? ':audio=best' : ''}`
        : `mode:${mode}${audio_mode === 'best' ? ':audio=best' : ''}`,
      status: 'processing',
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // 세션을 editing으로 전환 → Fly.io 폴링이 자동 감지
  await supabase
    .from('studio_sessions')
    .update({ status: 'editing', updated_at: new Date().toISOString() })
    .eq('id', id);

  return NextResponse.json({ ok: true, result });
}
