import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 테스트용 더미 클립 추가 (기존 Storage 영상 재사용)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: sessionId } = await params;
  const supabase = getServiceSupabase();

  // 세션 확인
  const { data: session } = await supabase
    .from('studio_sessions')
    .select('*')
    .eq('id', sessionId)
    .single();

  if (!session) {
    return NextResponse.json({ error: '세션을 찾을 수 없습니다' }, { status: 404 });
  }

  // Storage에서 기존 영상 찾기 (studio/ 하위의 모든 영상)
  const { data: folders } = await supabase.storage
    .from('studio-clips')
    .list('studio', { limit: 50 });

  let sourcePath: string | null = null;
  let sourceSize = 0;

  if (folders) {
    for (const folder of folders) {
      // 폴더 안의 파일 탐색
      const { data: files } = await supabase.storage
        .from('studio-clips')
        .list(`studio/${folder.name}`, { limit: 20 });

      if (files) {
        // 영상 파일 찾기 (.webm, .mp4)
        const videoFile = files.find(f =>
          (f.name.endsWith('.webm') || f.name.endsWith('.mp4')) &&
          !f.name.startsWith('result_')
        );
        if (videoFile) {
          sourcePath = `studio/${folder.name}/${videoFile.name}`;
          sourceSize = videoFile.metadata?.size || 0;
          break;
        }
      }
    }
  }

  if (!sourcePath) {
    return NextResponse.json({
      error: '재사용할 수 있는 기존 영상이 없습니다. 먼저 한 번 촬영해주세요.',
    }, { status: 404 });
  }

  // 현재 세션의 디바이스 수 확인 (카메라 인덱스 결정)
  const { data: existingDevices } = await supabase
    .from('studio_devices')
    .select('camera_index')
    .eq('session_id', sessionId)
    .order('camera_index', { ascending: false })
    .limit(1);

  const nextIndex = existingDevices?.length ? existingDevices[0].camera_index + 1 : 0;

  // 더미 디바이스 생성
  const { data: device, error: deviceErr } = await supabase
    .from('studio_devices')
    .insert({
      session_id: sessionId,
      name: `테스트 카메라 ${nextIndex + 1}`,
      camera_index: nextIndex,
      status: 'done',
    })
    .select()
    .single();

  if (deviceErr) {
    return NextResponse.json({ error: deviceErr.message }, { status: 500 });
  }

  // 기존 영상을 현재 세션 경로로 복사
  const ext = sourcePath.split('.').pop() || 'webm';
  const destPath = `studio/${sessionId}/${device.id}.${ext}`;

  const { data: sourceBlob } = await supabase.storage
    .from('studio-clips')
    .download(sourcePath);

  if (!sourceBlob) {
    return NextResponse.json({ error: '원본 영상 다운로드 실패' }, { status: 500 });
  }

  const buffer = Buffer.from(await sourceBlob.arrayBuffer());
  await supabase.storage
    .from('studio-clips')
    .upload(destPath, buffer, {
      contentType: ext === 'mp4' ? 'video/mp4' : 'video/webm',
      upsert: true,
    });

  // 클립 DB 등록
  const { data: clip, error: clipErr } = await supabase
    .from('studio_clips')
    .insert({
      session_id: sessionId,
      device_id: device.id,
      storage_path: destPath,
      duration_ms: 10000, // 기본 10초로 표시
      file_size: sourceSize || buffer.length,
    })
    .select()
    .single();

  if (clipErr) {
    return NextResponse.json({ error: clipErr.message }, { status: 500 });
  }

  // 세션이 아직 waiting/recording이면 uploading → done 으로 전환
  if (['waiting', 'recording', 'uploading'].includes(session.status)) {
    // 클립이 2개 이상이면 done으로 (편집 가능 상태)
    const { data: allClips } = await supabase
      .from('studio_clips')
      .select('id')
      .eq('session_id', sessionId);

    if (allClips && allClips.length >= 2) {
      await supabase
        .from('studio_sessions')
        .update({ status: 'done', updated_at: new Date().toISOString() })
        .eq('id', sessionId);
    }
  }

  return NextResponse.json({ ok: true, device, clip, sourcePath });
}
