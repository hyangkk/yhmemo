import { createClient } from '@supabase/supabase-js';
import { NextRequest, NextResponse } from 'next/server';
import { PADDLE_CONFIG } from '@/lib/paddle';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(req: NextRequest) {
  // 인증
  const authHeader = req.headers.get('authorization');
  if (!authHeader?.startsWith('Bearer ')) {
    return NextResponse.json({ error: 'Auth required' }, { status: 401 });
  }

  const token = authHeader.slice(7);
  const anonClient = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
  const { data: { user }, error: authError } = await anonClient.auth.getUser(token);

  if (authError || !user) {
    return NextResponse.json({ error: 'Auth failed' }, { status: 401 });
  }

  // 1. 활성 구독이 있으면 Paddle에서 취소
  const { data: profile } = await supabase
    .from('profiles')
    .select('paddle_subscription_id, plan')
    .eq('id', user.id)
    .single();

  if (profile?.paddle_subscription_id && profile.plan === 'plus' && PADDLE_CONFIG.apiKey) {
    const paddleUrl = PADDLE_CONFIG.environment === 'sandbox'
      ? 'https://sandbox-api.paddle.com'
      : 'https://api.paddle.com';

    await fetch(
      `${paddleUrl}/subscriptions/${profile.paddle_subscription_id}/cancel`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${PADDLE_CONFIG.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ effective_from: 'immediately' }),
      }
    ).catch(() => {}); // 실패해도 계속 진행
  }

  // 2. 사용자 데이터 삭제 (프로필, 결제 기록 등)
  await supabase.from('payments').delete().eq('user_id', user.id);
  await supabase.from('profiles').delete().eq('id', user.id);

  // 3. Supabase Auth에서 사용자 삭제
  const { error: deleteError } = await supabase.auth.admin.deleteUser(user.id);

  if (deleteError) {
    console.error('User deletion failed:', deleteError);
    return NextResponse.json({ error: 'Account deletion failed' }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
