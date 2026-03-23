import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: Paddle checkout 트랜잭션 기록 (Paddle.js가 프론트에서 처리)
export async function POST(req: NextRequest) {
  const { userId, projectId, transactionId, plan } = await req.json();
  const supabase = getServiceSupabase();

  const { data: payment, error } = await supabase
    .from('payments')
    .insert({
      user_id: userId,
      project_id: projectId,
      paddle_transaction_id: transactionId,
      feature: plan || 'plus',
      amount: 300, // $3 = 300 cents
      currency: 'usd',
      status: 'pending',
    })
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, paymentId: payment.id });
}
