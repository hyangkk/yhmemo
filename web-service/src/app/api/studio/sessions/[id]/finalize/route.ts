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

  // 세션을 done으로 전환
  await supabase
    .from('studio_sessions')
    .update({ status: 'done', updated_at: new Date().toISOString() })
    .eq('id', id);

  return NextResponse.json({ ok: true });
}
