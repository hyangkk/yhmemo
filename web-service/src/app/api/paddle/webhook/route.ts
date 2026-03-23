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
  const eventType = event.event_type;
  const data = event.data || {};
  const customData = data.custom_data || {};
  const userId = customData.user_id;

  // 구독 활성화
  if (eventType === 'subscription.activated' || eventType === 'transaction.completed') {
    if (userId) {
      const updates: Record<string, string> = { plan: 'plus' };
      if (data.id && eventType === 'subscription.activated') {
        updates.paddle_subscription_id = data.id;
      }
      if (data.customer_id) {
        updates.paddle_customer_id = data.customer_id;
      }

      await supabase
        .from('profiles')
        .update(updates)
        .eq('id', userId);

      // 결제 기록 업데이트
      const txId = data.transaction_id || data.id;
      if (txId) {
        await supabase
          .from('payments')
          .update({ status: 'completed' })
          .eq('paddle_transaction_id', txId);
      }
    }
  }

  // 구독 갱신 (매월 결제 성공)
  if (eventType === 'subscription.updated') {
    if (userId && data.status === 'active') {
      const updates: Record<string, string> = { plan: 'plus' };
      if (data.id) updates.paddle_subscription_id = data.id;
      await supabase.from('profiles').update(updates).eq('id', userId);
    }
  }

  // 구독 취소
  if (eventType === 'subscription.canceled') {
    if (userId) {
      await supabase
        .from('profiles')
        .update({ plan: 'free', paddle_subscription_id: null })
        .eq('id', userId);
    }
  }

  // 구독 일시정지
  if (eventType === 'subscription.paused') {
    if (userId) {
      await supabase
        .from('profiles')
        .update({ plan: 'free' })
        .eq('id', userId);
    }
  }

  // 구독 재개
  if (eventType === 'subscription.resumed') {
    if (userId) {
      await supabase
        .from('profiles')
        .update({ plan: 'plus' })
        .eq('id', userId);
    }
  }

  return NextResponse.json({ received: true });
}
