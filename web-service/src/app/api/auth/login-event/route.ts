import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { notifyServiceLog } from '@/lib/slack-notify';

// POST: 로그인 이벤트 기록 + 슬랙 알림
export async function POST(req: NextRequest) {
  try {
    const supabase = getServiceSupabase();

    const authHeader = req.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return NextResponse.json({ ok: false }, { status: 401 });
    }

    const token = authHeader.replace('Bearer ', '');
    const { data: { user } } = await supabase.auth.getUser(token);
    if (!user) {
      return NextResponse.json({ ok: false }, { status: 401 });
    }

    notifyServiceLog(`🔑 *로그인* | ${user.email}`);
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ ok: false }, { status: 500 });
  }
}
