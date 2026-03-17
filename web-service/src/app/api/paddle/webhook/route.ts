import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { PADDLE_CONFIG } from '@/lib/paddle';
import crypto from 'crypto';

// POST: Paddle Webhook
export async function POST(req: NextRequest) {
  const body = await req.text();
  const signature = req.headers.get('paddle-signature') || '';

  // 서명 검증
  if (PADDLE_CONFIG.webhookSecret) {
    try {
      const parts = signature.split(';');
      const tsStr = parts.find(p => p.startsWith('ts='))?.slice(3) || '';
      const h1 = parts.find(p => p.startsWith('h1='))?.slice(3) || '';
      const payload = `${tsStr}:${body}`;
      const expected = crypto.createHmac('sha256', PADDLE_CONFIG.webhookSecret).update(payload).digest('hex');
      if (h1 !== expected) {
        return NextResponse.json({ error: 'Invalid signature' }, { status: 401 });
      }
    } catch {
      return NextResponse.json({ error: 'Signature verification failed' }, { status: 401 });
    }
  }

  const event = JSON.parse(body);
  const supabase = getServiceSupabase();

  // 구독 활성화
  if (event.event_type === 'subscription.activated' || event.event_type === 'transaction.completed') {
    const customData = event.data?.custom_data;
    const userId = customData?.user_id;

    if (userId) {
      // 유저 플랜 업그레이드
      await supabase
        .from('profiles')
        .update({ plan: 'plus' })
        .eq('id', userId);

      // 결제 기록 업데이트
      const txId = event.data?.id || event.data?.transaction_id;
      if (txId) {
        await supabase
          .from('payments')
          .update({ status: 'completed', paddle_transaction_id: txId })
          .eq('paddle_transaction_id', txId);
      }
    }
  }

  // 구독 취소
  if (event.event_type === 'subscription.canceled') {
    const customData = event.data?.custom_data;
    const userId = customData?.user_id;
    if (userId) {
      await supabase
        .from('profiles')
        .update({ plan: 'free' })
        .eq('id', userId);
    }
  }

  return NextResponse.json({ received: true });
}
