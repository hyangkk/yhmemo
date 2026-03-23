import { NextResponse } from 'next/server';
import { PADDLE_CONFIG, PLANS } from '@/lib/paddle';

// GET: Paddle 결제 가능 여부 종합 진단
export async function GET() {
  const apiKey = PADDLE_CONFIG.apiKey;
  if (!apiKey) {
    return NextResponse.json({ ok: false, error: 'PADDLE_API_KEY 미설정' });
  }

  const baseUrl = PADDLE_CONFIG.environment === 'sandbox'
    ? 'https://sandbox-api.paddle.com'
    : 'https://api.paddle.com';
  const headers = {
    'Authorization': `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
  };

  const results: Record<string, unknown> = { environment: PADDLE_CONFIG.environment };

  // 1. 트랜잭션 생성 시도 (결제 가능 여부 실제 확인)
  try {
    const txRes = await fetch(`${baseUrl}/transactions`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        items: [{
          price_id: PLANS.plus.priceId,
          quantity: 1,
        }],
      }),
    });
    const txData = await txRes.json();
    if (txRes.ok) {
      results.transactionTest = {
        ok: true,
        status: txData.data?.status,
        id: txData.data?.id,
        checkout_url: txData.data?.checkout?.url,
      };
    } else {
      results.transactionTest = {
        ok: false,
        status: txRes.status,
        error: txData.error,
      };
    }
  } catch (e) {
    results.transactionTest = { ok: false, error: String(e) };
  }

  // 2. 이벤트 로그 확인 (최근 오류)
  try {
    const evRes = await fetch(`${baseUrl}/events?per_page=5&order_by=occurred_at[DESC]`, { headers });
    if (evRes.ok) {
      const evData = await evRes.json();
      results.recentEvents = evData.data?.map((e: { event_type: string; occurred_at: string }) => ({
        type: e.event_type,
        at: e.occurred_at,
      }));
    }
  } catch { /* ignore */ }

  // 3. 도메인/허용 URL 관련 설정
  try {
    const domRes = await fetch(`${baseUrl}/notification-settings`, { headers });
    if (domRes.ok) {
      const domData = await domRes.json();
      results.notificationSettings = domData.data;
    }
  } catch { /* ignore */ }

  // 4. 비즈니스 정보 확인
  try {
    const bizRes = await fetch(`${baseUrl}/businesses?per_page=5`, { headers });
    if (bizRes.ok) {
      const bizData = await bizRes.json();
      results.businesses = bizData.data;
    }
  } catch { /* ignore */ }

  // 5. 고객 정보 확인
  try {
    const custRes = await fetch(`${baseUrl}/customers?per_page=3`, { headers });
    if (custRes.ok) {
      const custData = await custRes.json();
      results.customers = custData.data?.map((c: { id: string; email: string; status: string }) => ({
        id: c.id,
        email: c.email,
        status: c.status,
      }));
    }
  } catch { /* ignore */ }

  return NextResponse.json(results);
}
