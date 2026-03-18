import { createClient } from '@supabase/supabase-js';
import { NextRequest, NextResponse } from 'next/server';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

// 테스트 기간: 결제 없이 즉시 구독 취소 (plan → free)
export async function POST(req: NextRequest) {
  const authHeader = req.headers.get('authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return NextResponse.json({ error: '인증 필요' }, { status: 401 });
  }

  const token = authHeader.slice(7);
  const anonClient = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
  const { data: { user }, error: authError } = await anonClient.auth.getUser(token);

  if (authError || !user) {
    return NextResponse.json({ error: '인증 실패' }, { status: 401 });
  }

  const { error } = await supabase
    .from('profiles')
    .update({ plan: 'free' })
    .eq('id', user.id);

  if (error) {
    return NextResponse.json({ error: '구독 취소 실패' }, { status: 500 });
  }

  return NextResponse.json({ plan: 'free' });
}
