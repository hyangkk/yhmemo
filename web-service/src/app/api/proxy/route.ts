import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

// 허용 도메인 화이트리스트 (한국 사이트)
const ALLOWED_DOMAINS = [
  "yicare.or.kr",
  "www.yicare.or.kr",
];

export async function POST(request: NextRequest) {
  try {
    // 인증: SUPABASE_SERVICE_ROLE_KEY를 Bearer 토큰으로 사용
    const authHeader = request.headers.get("authorization");
    const expectedKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (!expectedKey || !authHeader || authHeader !== `Bearer ${expectedKey}`) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const body = await request.json();
    const { url } = body;

    if (!url || typeof url !== "string") {
      return NextResponse.json({ error: "url 필수" }, { status: 400 });
    }

    // 도메인 화이트리스트 검증
    let parsedUrl: URL;
    try {
      parsedUrl = new URL(url);
    } catch {
      return NextResponse.json({ error: "잘못된 URL" }, { status: 400 });
    }

    const hostname = parsedUrl.hostname.toLowerCase();
    if (!ALLOWED_DOMAINS.some((d) => hostname === d || hostname.endsWith(`.${d}`))) {
      return NextResponse.json(
        { error: `허용되지 않은 도메인: ${hostname}` },
        { status: 403 }
      );
    }

    // 한국 브라우저 User-Agent로 페이지 fetch
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        Accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
      },
      redirect: "follow",
    });

    const contentType = response.headers.get("content-type") || "";
    const buffer = await response.arrayBuffer();

    // EUC-KR 등 인코딩 처리
    let html: string;
    if (contentType.includes("euc-kr") || contentType.includes("euc_kr")) {
      const decoder = new TextDecoder("euc-kr");
      html = decoder.decode(buffer);
    } else {
      html = new TextDecoder("utf-8").decode(buffer);
      // UTF-8 디코딩 후 meta 태그에서 EUC-KR 감지
      if (html.includes("euc-kr") || html.includes("EUC-KR")) {
        const decoder = new TextDecoder("euc-kr");
        html = decoder.decode(buffer);
      }
    }

    return NextResponse.json({
      status: response.status,
      html,
      content_type: contentType,
      url: response.url,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
