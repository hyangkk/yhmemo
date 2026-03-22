import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  const hostname = request.headers.get('host') || '';
  const pathname = request.nextUrl.pathname;

  // supacam.vercel.app 도메인에서 루트 접근 시 SupaCam 랜딩 페이지로 rewrite
  if (hostname.includes('supacam') && pathname === '/') {
    return NextResponse.rewrite(new URL('/supacam-home', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/'],
};
