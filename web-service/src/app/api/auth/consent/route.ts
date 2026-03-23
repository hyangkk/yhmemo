import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { notifyServiceLog } from '@/lib/slack-notify';

// POST: 약관 동의 처리
export async function POST(req: NextRequest) {
  try {
    const supabase = getServiceSupabase();

    const authHeader = req.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const token = authHeader.replace('Bearer ', '');
    const { data: { user }, error: authError } = await supabase.auth.getUser(token);
    if (authError || !user) {
      return NextResponse.json({ error: 'Invalid token' }, { status: 401 });
    }

    // profiles 테이블에 약관 동의 일시 기록
    const { error } = await supabase
      .from('profiles')
      .update({ terms_agreed_at: new Date().toISOString() })
      .eq('id', user.id);

    if (error) {
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    // 슬랙 알림: 회원가입 (약관 동의)
    notifyServiceLog(`🎉 *회원가입* | ${user.email}`);

    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ error: 'Server error' }, { status: 500 });
  }
}

// GET: 약관 동의 상태 확인
export async function GET(req: NextRequest) {
  try {
    const supabase = getServiceSupabase();

    const authHeader = req.headers.get('authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return NextResponse.json({ agreed: false });
    }

    const token = authHeader.replace('Bearer ', '');
    const { data: { user } } = await supabase.auth.getUser(token);
    if (!user) {
      return NextResponse.json({ agreed: false });
    }

    const { data: profile } = await supabase
      .from('profiles')
      .select('terms_agreed_at')
      .eq('id', user.id)
      .single();

    return NextResponse.json({ agreed: !!profile?.terms_agreed_at });
  } catch {
    return NextResponse.json({ agreed: false });
  }
}
