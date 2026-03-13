import { NextResponse } from 'next/server';

const STUDIO_API = 'https://yhmbp14.fly.dev';

// GET: 프론트/서버 빌드 번호 조회
export async function GET() {
  const front = process.env.NEXT_PUBLIC_BUILD_NUM || '0';

  let server = '?';
  try {
    const res = await fetch(`${STUDIO_API}/health`, {
      next: { revalidate: 0 },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      server = data.build_num || '?';
    }
  } catch {}

  return NextResponse.json({ front, server });
}
