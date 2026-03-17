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
    const storagePath = `projects/${projectId}/${memberId}_${clipId}.${ext || 'webm'}`;

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
