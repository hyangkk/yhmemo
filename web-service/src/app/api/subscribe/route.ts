import { NextResponse } from 'next/server';

// 구독은 Paddle 결제를 통해서만 가능합니다.
// /api/paddle/checkout 또는 Paddle Webhook을 통해 처리됩니다.
export async function POST() {
  return NextResponse.json(
    { error: 'Please use Paddle checkout to subscribe.' },
    { status: 410 }
  );
}
