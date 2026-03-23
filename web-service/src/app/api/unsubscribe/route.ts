import { createClient } from '@supabase/supabase-js';
import { NextRequest, NextResponse } from 'next/server';
import { PADDLE_CONFIG } from '@/lib/paddle';
import { notifyServiceLog } from '@/lib/slack-notify';

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

  // 프로필에서 subscription_id 조회
  const { data: profile } = await supabase
    .from('profiles')
    .select('paddle_subscription_id, plan')
    .eq('id', user.id)
    .single();

  if (!profile || profile.plan !== 'plus') {
    return NextResponse.json({ error: 'No active subscription' }, { status: 400 });
  }

  // Paddle API로 구독 취소 (API Key가 있는 경우)
  if (profile.paddle_subscription_id && PADDLE_CONFIG.apiKey) {
    const paddleUrl = PADDLE_CONFIG.environment === 'sandbox'
      ? 'https://sandbox-api.paddle.com'
      : 'https://api.paddle.com';

    const cancelRes = await fetch(
      `${paddleUrl}/subscriptions/${profile.paddle_subscription_id}/cancel`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${PADDLE_CONFIG.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ effective_from: 'next_billing_period' }),
      }
    );

    if (!cancelRes.ok) {
      const err = await cancelRes.text();
      console.error('Paddle cancel failed:', err);
      // Paddle 취소 실패해도 DB는 업데이트 (fallback)
    }
  }

  // DB에서 즉시 free로 전환
  await supabase
    .from('profiles')
    .update({ plan: 'free' })
    .eq('id', user.id);

  notifyServiceLog(`🚫 *구독 취소* | ${user.email || user.id}`);

  return NextResponse.json({ plan: 'free' });
}
