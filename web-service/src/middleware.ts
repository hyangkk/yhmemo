import { NextRequest, NextResponse } from 'next/server';

export function middleware(request: NextRequest) {
  const hostname = request.headers.get('host') || '';
  const pathname = request.nextUrl.pathname;

  if (hostname.includes('supacam')) {
    // supacam 도메인: 루트 → SupaCam 랜딩 페이지
    if (pathname === '/') {
      return NextResponse.rewrite(new URL('/supacam-home', request.url));
    }

    // supacam 도메인: YH Hub 전용 페이지 접근 차단 → /studio로 리다이렉트
    if (pathname === '/projects' || pathname === '/dashboard' || pathname === '/invest' || pathname === '/family') {
      return NextResponse.redirect(new URL('/studio', request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/', '/projects', '/dashboard', '/invest', '/family'],
};
