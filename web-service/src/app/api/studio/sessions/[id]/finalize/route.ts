import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: stuck된 uploading 세션을 강제 완료 처리
export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();

  // stuck된 디바이스 (done/error가 아닌 것)를 error로 변경
  await supabase
    .from('studio_devices')
    .update({ status: 'error' })
    .eq('session_id', id)
    .not('status', 'in', '("done","error")');

  // 업로드 성공한 클립이 있는지 확인
  const { data: clips } = await supabase
    .from('studio_clips')
    .select('id')
    .eq('session_id', id);

  if (clips && clips.length > 0) {
    // 클립이 있으면 editing으로 전환 → Fly.io 폴링 서버가 편집 실행
    await supabase
      .from('studio_sessions')
      .update({ status: 'editing', updated_at: new Date().toISOString() })
      .eq('id', id);
  } else {
    // 클립 없으면 done으로 전환
    await supabase
      .from('studio_sessions')
      .update({ status: 'done', updated_at: new Date().toISOString() })
      .eq('id', id);
  }

  return NextResponse.json({ ok: true });
}
