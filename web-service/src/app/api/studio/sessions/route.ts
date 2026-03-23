import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { generateSessionCode } from '@/lib/studio';
import { notifyServiceLog } from '@/lib/slack-notify';

// POST: 새 세션 생성
export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const title = body.title || '새 촬영';
    const supabase = getServiceSupabase();

    // 인증된 사용자 ID 추출 (선택적)
    let createdBy: string | null = null;
    const authHeader = req.headers.get('authorization');
    if (authHeader?.startsWith('Bearer ')) {
      const token = authHeader.replace('Bearer ', '');
      const { data: { user } } = await supabase.auth.getUser(token);
      if (user) createdBy = user.id;
    }

    // 유니크 코드 생성 (충돌 시 재시도)
    let code = generateSessionCode();
    let retries = 0;
    while (retries < 5) {
      const { data: existing } = await supabase
        .from('studio_sessions')
        .select('id')
        .eq('code', code)
        .single();
      if (!existing) break;
      code = generateSessionCode();
      retries++;
    }

    const { data, error } = await supabase
      .from('studio_sessions')
      .insert({ code, title, created_by: createdBy })
      .select()
      .single();

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // 슬랙 알림: 새 촬영 시작
    const userEmail = createdBy ? `(user: ${createdBy.slice(0, 8)}...)` : '(비로그인)';
    notifyServiceLog(`📹 *새 촬영* | "${title}" ${userEmail}`);

    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: '세션 생성 실패' }, { status: 500 });
  }
}

// GET: 코드로 세션 조회
export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get('code');
  if (!code) {
    return NextResponse.json({ error: '코드가 필요합니다' }, { status: 400 });
  }

  const supabase = getServiceSupabase();
  const { data, error } = await supabase
    .from('studio_sessions')
    .select('*')
    .eq('code', code.trim())
    .single();

  if (error || !data) {
    return NextResponse.json({ error: '세션을 찾을 수 없습니다' }, { status: 404 });
  }

  return NextResponse.json(data);
}
