import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 편집 실패 시 재시도 - 세션을 editing으로 되돌려 백엔드 폴링이 다시 편집 실행
export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();

  // 기존 에러 결과 삭제
  await supabase
    .from('studio_results')
    .delete()
    .eq('session_id', id)
    .eq('status', 'error');

  // 세션을 editing으로 되돌림 → Fly.io 폴링 서버가 자동으로 편집 재시도
  await supabase
    .from('studio_sessions')
    .update({ status: 'editing', updated_at: new Date().toISOString() })
    .eq('id', id);

  // 새 result row 반환 (프론트엔드에서 UI 즉시 업데이트용)
  return NextResponse.json({
    ok: true,
    result: { status: 'processing', storage_path: '' },
  });
}
