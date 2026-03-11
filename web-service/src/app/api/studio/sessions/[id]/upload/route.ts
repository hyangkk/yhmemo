import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 업로드 URL 발급 또는 메타데이터 기록
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id: sessionId } = await params;
    const contentType = req.headers.get('content-type') || '';

    // JSON 요청 = signed URL 발급 또는 메타데이터 기록
    if (contentType.includes('application/json')) {
      const body = await req.json();
      const supabase = getServiceSupabase();

      // phase=url → signed upload URL 발급
      if (body.phase === 'url') {
        const { deviceId, ext } = body;
        if (!deviceId) {
          return NextResponse.json({ error: 'deviceId가 필요합니다' }, { status: 400 });
        }

        const storagePath = `studio/${sessionId}/${deviceId}.${ext || 'webm'}`;

        // 기존 파일이 있으면 삭제 (upsert 대신 - signed URL은 upsert 미지원)
        await supabase.storage.from('studio-clips').remove([storagePath]);

        const { data, error } = await supabase.storage
          .from('studio-clips')
          .createSignedUploadUrl(storagePath);

        if (error) {
          return NextResponse.json({ error: `URL 생성 실패: ${error.message}` }, { status: 500 });
        }

        return NextResponse.json({
          signedUrl: data.signedUrl,
          token: data.token,
          path: data.path,
          storagePath,
        });
      }

      // phase=confirm → 업로드 완료 후 메타데이터 기록
      if (body.phase === 'confirm') {
        const { deviceId, durationMs, fileSize, storagePath } = body;
        if (!deviceId || !storagePath) {
          return NextResponse.json({ error: 'deviceId와 storagePath가 필요합니다' }, { status: 400 });
        }

        // DB에 클립 기록
        const { data: clip, error: dbError } = await supabase
          .from('studio_clips')
          .insert({
            session_id: sessionId,
            device_id: deviceId,
            storage_path: storagePath,
            duration_ms: durationMs || 0,
            file_size: fileSize || 0,
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

        const allFinished = allDevices?.every(d => d.status === 'done' || d.status === 'error');
        const hasClips = allDevices?.some(d => d.status === 'done');

        if (allFinished && hasClips) {
          await supabase
            .from('studio_sessions')
            .update({ status: 'editing', updated_at: new Date().toISOString() })
            .eq('id', sessionId);
        } else if (allFinished && !hasClips) {
          await supabase
            .from('studio_sessions')
            .update({ status: 'done', updated_at: new Date().toISOString() })
            .eq('id', sessionId);
        }

        return NextResponse.json({ clip, allUploaded: allFinished });
      }

      return NextResponse.json({ error: 'phase 파라미터가 필요합니다 (url 또는 confirm)' }, { status: 400 });
    }

    // FormData 요청 = 레거시 직접 업로드 (호환성 유지)
    const formData = await req.formData();
    const file = formData.get('video') as File;
    const deviceId = formData.get('deviceId') as string;
    const durationMs = parseInt(formData.get('durationMs') as string) || 0;

    if (!file || !deviceId) {
      return NextResponse.json({ error: '영상 파일과 deviceId가 필요합니다' }, { status: 400 });
    }

    const supabase = getServiceSupabase();

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

    await supabase
      .from('studio_devices')
      .update({ status: 'done' })
      .eq('id', deviceId);

    const { data: allDevices } = await supabase
      .from('studio_devices')
      .select('status')
      .eq('session_id', sessionId);

    const allFinished = allDevices?.every(d => d.status === 'done' || d.status === 'error');
    const hasClips = allDevices?.some(d => d.status === 'done');

    if (allFinished && hasClips) {
      await supabase
        .from('studio_sessions')
        .update({ status: 'editing', updated_at: new Date().toISOString() })
        .eq('id', sessionId);
    } else if (allFinished && !hasClips) {
      await supabase
        .from('studio_sessions')
        .update({ status: 'done', updated_at: new Date().toISOString() })
        .eq('id', sessionId);
    }

    return NextResponse.json({ clip, allUploaded: allFinished });
  } catch {
    return NextResponse.json({ error: '업로드 처리 실패' }, { status: 500 });
  }
}
