/**
 * Supabase Edge Function: kr-proxy
 *
 * 한국 전용 사이트에 대한 HTTP 프록시.
 * Supabase Edge Function은 글로벌 CDN(Deno Deploy)에서 실행되며,
 * 한국 엣지 노드를 통해 한국 IP로 접근 가능.
 *
 * 사용: POST /functions/v1/kr-proxy
 * Body: { "url": "https://www.yicare.or.kr/..." }
 * Header: Authorization: Bearer <SUPABASE_SERVICE_ROLE_KEY>
 */

const ALLOWED_DOMAINS = [
  "yicare.or.kr",
  "www.yicare.or.kr",
];

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, content-type",
};

Deno.serve(async (req: Request) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "POST만 허용" }),
      { status: 405, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } },
    );
  }

  // 인증 확인 (Supabase가 자동으로 JWT 검증하므로 여기 도달하면 인증 완료)
  try {
    const body = await req.json();
    const url = body.url;

    if (!url || typeof url !== "string") {
      return new Response(
        JSON.stringify({ error: "url 필수" }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } },
      );
    }

    // 도메인 화이트리스트 검증
    let parsedUrl: URL;
    try {
      parsedUrl = new URL(url);
    } catch {
      return new Response(
        JSON.stringify({ error: "잘못된 URL" }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } },
      );
    }

    const hostname = parsedUrl.hostname.toLowerCase();
    if (!ALLOWED_DOMAINS.some((d) => hostname === d || hostname.endsWith(`.${d}`))) {
      return new Response(
        JSON.stringify({ error: `허용되지 않은 도메인: ${hostname}` }),
        { status: 403, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } },
      );
    }

    // 한국 브라우저 User-Agent + X-Forwarded-For로 페이지 fetch
    const response = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept":
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
      },
      redirect: "follow",
    });

    const contentType = response.headers.get("content-type") || "";
    const buffer = await response.arrayBuffer();

    // EUC-KR 등 인코딩 처리
    let html: string;
    if (contentType.includes("euc-kr") || contentType.includes("euc_kr")) {
      html = new TextDecoder("euc-kr").decode(buffer);
    } else {
      html = new TextDecoder("utf-8").decode(buffer);
      // UTF-8 디코딩 후 meta 태그에서 EUC-KR 감지
      if (html.includes("euc-kr") || html.includes("EUC-KR")) {
        html = new TextDecoder("euc-kr").decode(buffer);
      }
    }

    return new Response(
      JSON.stringify({
        status: response.status,
        html,
        content_type: contentType,
        url: response.url,
      }),
      {
        status: 200,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      },
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return new Response(
      JSON.stringify({ error: message }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } },
    );
  }
});
