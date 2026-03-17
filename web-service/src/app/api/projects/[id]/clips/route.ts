import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: 클립 업로드 (signed URL 발급 또는 메타데이터 기록)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: projectId } = await params;
  const supabase = getServiceSupabase();
  const body = await req.json();

  // phase=url → signed upload URL 발급
  if (body.phase === 'url') {
    const { memberId, clipId, ext } = body;
    // 경로 순회 공격 방지: UUID 형식 검증 + 확장자 화이트리스트
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(memberId) || !uuidRegex.test(clipId)) {
      return NextResponse.json({ error: 'memberId/clipId 형식이 올바르지 않습니다' }, { status: 400 });
    }
    const allowedExts = ['webm', 'mp4', 'mov', 'avi'];
    const safeExt = allowedExts.includes(ext) ? ext : 'webm';
    const storagePath = `projects/${projectId}/${memberId}_${clipId}.${safeExt}`;

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

  // phase=confirm → 클립 메타데이터 기록
  if (body.phase === 'confirm') {
    const { memberId, durationMs, fileSize, storagePath, startedAt, endedAt } = body;

    const { data: clip, error } = await supabase
      .from('project_clips')
      .insert({
        project_id: projectId,
        member_id: memberId,
        storage_path: storagePath,
        duration_ms: durationMs || 0,
        file_size: fileSize || 0,
        started_at: startedAt,
        ended_at: endedAt || null,
      })
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // 프로젝트 updated_at 갱신
    await supabase
      .from('projects')
      .update({ updated_at: new Date().toISOString() })
      .eq('id', projectId);

    return NextResponse.json({ clip });
  }

  return NextResponse.json({ error: 'phase 파라미터가 필요합니다' }, { status: 400 });
}
