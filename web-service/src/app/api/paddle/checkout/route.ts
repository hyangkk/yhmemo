import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { notifyServiceLog } from '@/lib/slack-notify';

// POST: Paddle checkout 완료 후 트랜잭션 기록 + 즉시 플랜 활성화
export async function POST(req: NextRequest) {
  const { userId, projectId, transactionId, plan } = await req.json();

  if (!userId || !transactionId) {
    return NextResponse.json({ error: 'userId and transactionId required' }, { status: 400 });
  }

  const supabase = getServiceSupabase();

  // 1. 결제 기록 저장
  const { data: payment, error: paymentError } = await supabase
    .from('payments')
    .insert({
      user_id: userId,
      project_id: projectId || null,
      paddle_transaction_id: transactionId,
      feature: plan || 'plus',
      amount: 300, // $3 = 300 cents
      currency: 'usd',
      status: 'completed',
    })
    .select()
    .single();

  if (paymentError) {
    return NextResponse.json({ error: paymentError.message }, { status: 500 });
  }

  // 2. 즉시 플랜 업그레이드 (webhook 도착 전이라도 UX 개선)
  await supabase
    .from('profiles')
    .update({ plan: 'plus' })
    .eq('id', userId);

  // 3. 유저 이메일 조회 후 슬랙 알림
  const { data: profile } = await supabase.from('profiles').select('email').eq('id', userId).single();
  notifyServiceLog(`💳 *결제 완료* | ${profile?.email || userId} → Plus ($3/mo) | tx: ${transactionId}`);

  return NextResponse.json({ ok: true, paymentId: payment.id });
}
