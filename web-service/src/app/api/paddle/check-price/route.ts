import { NextResponse } from 'next/server';
import { PADDLE_CONFIG, PLANS } from '@/lib/paddle';

// GET: Paddle Price + Product + Seller 종합 검증
export async function GET() {
  const priceId = PLANS.plus.priceId;
  const apiKey = PADDLE_CONFIG.apiKey;

  if (!priceId) {
    return NextResponse.json({ ok: false, error: 'Price ID가 설정되지 않았습니다.' });
  }

  if (!apiKey) {
    return NextResponse.json({ ok: true, skipped: true, reason: 'API key not configured' });
  }

  const baseUrl = PADDLE_CONFIG.environment === 'sandbox'
    ? 'https://sandbox-api.paddle.com'
    : 'https://api.paddle.com';

  const headers = { Authorization: `Bearer ${apiKey}` };

  try {
    // 1. Price 확인
    const priceRes = await fetch(`${baseUrl}/prices/${priceId}?include=product`, { headers });

    if (!priceRes.ok) {
      const err = await priceRes.json().catch(() => ({}));
      return NextResponse.json({
        ok: false,
        error: `Price 조회 실패 (${priceRes.status})`,
        detail: err,
      });
    }

    const priceData = (await priceRes.json()).data;

    // 2. Product 확인
    let productData = priceData.product;
    if (!productData && priceData.product_id) {
      const prodRes = await fetch(`${baseUrl}/products/${priceData.product_id}`, { headers });
      if (prodRes.ok) {
        productData = (await prodRes.json()).data;
      }
    }

    // 3. 최근 트랜잭션 확인 (결제 가능 여부 간접 확인)
    let recentTx = null;
    try {
      const txRes = await fetch(`${baseUrl}/transactions?per_page=1&order_by=created_at[DESC]`, { headers });
      if (txRes.ok) {
        const txData = await txRes.json();
        recentTx = txData.data?.[0] ? {
          id: txData.data[0].id,
          status: txData.data[0].status,
          created_at: txData.data[0].created_at,
        } : null;
      }
    } catch { /* ignore */ }

    // 4. Notification settings 확인 (webhook 설정)
    let notifications = null;
    try {
      const notiRes = await fetch(`${baseUrl}/notification-settings`, { headers });
      if (notiRes.ok) {
        const notiData = await notiRes.json();
        notifications = notiData.data?.map((n: { id: string; destination: string; active: boolean }) => ({
          id: n.id,
          destination: n.destination,
          active: n.active,
        }));
      }
    } catch { /* ignore */ }

    const issues: string[] = [];

    if (priceData.status !== 'active') {
      issues.push(`Price 비활성 (${priceData.status})`);
    }
    if (productData && productData.status !== 'active') {
      issues.push(`Product 비활성 (${productData.status})`);
    }
    if (!productData) {
      issues.push('Product 정보 없음');
    }

    return NextResponse.json({
      ok: issues.length === 0,
      issues,
      price: {
        id: priceData.id,
        status: priceData.status,
        description: priceData.description,
        unitPrice: priceData.unit_price,
        billingCycle: priceData.billing_cycle,
        productId: priceData.product_id,
      },
      product: productData ? {
        id: productData.id,
        name: productData.name,
        status: productData.status,
        taxCategory: productData.tax_category,
      } : null,
      recentTransaction: recentTx,
      webhooks: notifications,
      environment: PADDLE_CONFIG.environment,
    });
  } catch (err) {
    console.error('[Paddle] Check error:', err);
    return NextResponse.json({ ok: true, skipped: true, reason: 'Network error' });
  }
}
