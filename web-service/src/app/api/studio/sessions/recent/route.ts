import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

export async function GET(req: NextRequest) {
  try {
    const supabase = getServiceSupabase();

    // 인증된 사용자의 세션만 반환
    const authHeader = req.headers.get('authorization');
    let userId: string | null = null;
    if (authHeader?.startsWith('Bearer ')) {
      const token = authHeader.replace('Bearer ', '');
      const { data: { user } } = await supabase.auth.getUser(token);
      if (user) userId = user.id;
    }

    // 미인증 시 빈 배열 반환
    if (!userId) {
      return NextResponse.json([]);
    }

    const { data, error } = await supabase
      .from('studio_sessions')
      .select('id, title, status, created_at, studio_results(id, storage_path, duration_ms, status), studio_clips(id)')
      .eq('created_by', userId)
      .in('status', ['done', 'editing'])
      .order('created_at', { ascending: false })
      .limit(10);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json(data || []);
  } catch {
    return NextResponse.json([], { status: 500 });
  }
}
