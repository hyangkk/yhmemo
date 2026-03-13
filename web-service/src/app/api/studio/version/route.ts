import { NextResponse } from 'next/server';

const STUDIO_API = 'https://yhmbp14.fly.dev';

// GET: 프론트/서버 빌드 버전 조회
export async function GET() {
  const frontSha = process.env.NEXT_PUBLIC_BUILD_SHA || 'dev';

  let serverSha = '?';
  try {
    const res = await fetch(`${STUDIO_API}/health`, {
      next: { revalidate: 0 },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      serverSha = data.build_sha || '?';
    }
  } catch {}

  return NextResponse.json({ front: frontSha, server: serverSha });
}
