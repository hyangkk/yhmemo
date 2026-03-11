import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 영상 클립 업로드
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: sessionId } = await params;
    const formData = await req.formData();
    const file = formData.get('video') as File;
    const deviceId = formData.get('deviceId') as string;
    const durationMs = parseInt(formData.get('durationMs') as string) || 0;

    if (!file || !deviceId) {
      return NextResponse.json({ error: '영상 파일과 deviceId가 필요합니다' }, { status: 400 });
    }

    const supabase = getServiceSupabase();

    // Storage에 업로드
    const ext = file.type.includes('mp4') ? 'mp4' : 'webm';
    const storagePath = `studio/${sessionId}/${deviceId}.${ext}`;

    const buffer = Buffer.from(await file.arrayBuffer());
    const { error: uploadError } = await supabase.storage
      .from('studio-clips')
      .upload(storagePath, buffer, {
        contentType: file.type,
        upsert: true,
      });

    if (uploadError) {
      return NextResponse.json({ error: `업로드 실패: ${uploadError.message}` }, { status: 500 });
    }

    // DB에 클립 기록
    const { data: clip, error: dbError } = await supabase
      .from('studio_clips')
      .insert({
        session_id: sessionId,
        device_id: deviceId,
        storage_path: storagePath,
        duration_ms: durationMs,
        file_size: file.size,
      })
      .select()
      .single();

    if (dbError) {
      return NextResponse.json({ error: dbError.message }, { status: 500 });
    }

    // 디바이스 상태 업데이트
    await supabase
      .from('studio_devices')
      .update({ status: 'done' })
      .eq('id', deviceId);

    // 모든 디바이스 업로드 완료 여부 확인
    const { data: allDevices } = await supabase
      .from('studio_devices')
      .select('status')
      .eq('session_id', sessionId);

    const allDone = allDevices?.every(d => d.status === 'done');

    if (allDone) {
      // 모든 업로드 완료 → Fly.io 편집 서버에 자동 편집 요청
      const studioServerUrl = process.env.STUDIO_SERVER_URL || 'https://yhmemo-studio.fly.dev';
      try {
        await fetch(`${studioServerUrl}/edit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, mode: 'auto' }),
        });
      } catch (editErr) {
        console.error('편집 서버 호출 실패:', editErr);
        // 편집 서버 호출 실패해도 업로드는 성공으로 처리
      }
    }

    return NextResponse.json({ clip, allUploaded: allDone });
  } catch {
    return NextResponse.json({ error: '업로드 처리 실패' }, { status: 500 });
  }
}
