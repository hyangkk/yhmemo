import { NextResponse } from 'next/server';
import { PADDLE_CONFIG, PLANS } from '@/lib/paddle';

// GET: Paddle Price 유효성 검증
export async function GET() {
  const priceId = PLANS.plus.priceId;
  const apiKey = PADDLE_CONFIG.apiKey;

  if (!priceId) {
    return NextResponse.json({ ok: false, error: 'Price ID가 설정되지 않았습니다.' });
  }

  if (!apiKey) {
    // API 키 없으면 검증 스킵 (checkout은 시도 허용)
    return NextResponse.json({ ok: true, skipped: true, reason: 'API key not configured' });
  }

  const baseUrl = PADDLE_CONFIG.environment === 'sandbox'
    ? 'https://sandbox-api.paddle.com'
    : 'https://api.paddle.com';

  try {
    const res = await fetch(`${baseUrl}/prices/${priceId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
      next: { revalidate: 60 }, // 1분 캐시
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      console.error('[Paddle] Price check failed:', res.status, err);

      if (res.status === 404) {
        return NextResponse.json({
          ok: false,
          error: '등록된 요금제를 찾을 수 없습니다. Paddle 대시보드에서 Price ID를 확인해주세요.',
          detail: { priceId, environment: PADDLE_CONFIG.environment },
        });
      }

      if (res.status === 401) {
        return NextResponse.json({
          ok: false,
          error: 'Paddle API 인증 실패. API 키를 확인해주세요.',
        });
      }

      return NextResponse.json({
        ok: false,
        error: `Paddle API 오류 (${res.status})`,
        detail: err,
      });
    }

    const { data } = await res.json();

    if (data.status !== 'active') {
      return NextResponse.json({
        ok: false,
        error: `요금제가 비활성 상태입니다 (${data.status}). Paddle 대시보드에서 활성화해주세요.`,
        detail: { priceId, status: data.status },
      });
    }

    return NextResponse.json({
      ok: true,
      price: {
        id: data.id,
        status: data.status,
        description: data.description,
        unitPrice: data.unit_price,
        billingCycle: data.billing_cycle,
      },
    });
  } catch (err) {
    console.error('[Paddle] Price check error:', err);
    // 네트워크 오류 시 checkout은 시도 허용
    return NextResponse.json({ ok: true, skipped: true, reason: 'Network error' });
  }
}
