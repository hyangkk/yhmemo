import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: stuck된 uploading 세션을 강제 완료 처리
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();

  let force = false;
  try {
    const body = await req.json();
    force = body.force === true;
  } catch {
    // body 없으면 기본 동작 (비강제)
  }

  // 현재 디바이스 상태 확인
  const { data: devices } = await supabase
    .from('studio_devices')
    .select('id, status')
    .eq('session_id', id);

  if (devices) {
    const stillUploading = devices.filter(d => d.status === 'uploading');
    const stuck = devices.filter(d =>
      d.status !== 'done' && d.status !== 'error' && d.status !== 'uploading'
    );

    // stuck 디바이스 (connected, waiting 등)는 항상 error로
    if (stuck.length > 0) {
      await supabase
        .from('studio_devices')
        .update({ status: 'error' })
        .eq('session_id', id)
        .in('id', stuck.map(d => d.id));
    }

    // force가 아니면 uploading 중인 디바이스 기다림
    if (!force && stillUploading.length > 0) {
      return NextResponse.json({ ok: true, waiting: stillUploading.length });
    }

    // force: uploading 디바이스도 error 처리 (타임아웃)
    if (force && stillUploading.length > 0) {
      await supabase
        .from('studio_devices')
        .update({ status: 'error' })
        .eq('session_id', id)
        .in('id', stillUploading.map(d => d.id));
    }
  }

  // 모든 디바이스 완료 → 편집 전환
  const { data: clips } = await supabase
    .from('studio_clips')
    .select('id')
    .eq('session_id', id);

  if (clips && clips.length > 0) {
    // 업로드 완료 → done 상태로 전환 (편집 설정 패널 표시)
    // 사용자가 설정 후 "편집하기" 클릭 시 editing으로 전환됨
    await supabase
      .from('studio_sessions')
      .update({ status: 'done', updated_at: new Date().toISOString() })
      .eq('id', id);
  } else {
    await supabase
      .from('studio_sessions')
      .update({ status: 'done', updated_at: new Date().toISOString() })
      .eq('id', id);
  }

  return NextResponse.json({ ok: true });
}
