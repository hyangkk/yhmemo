/**
 * Cloudflare Worker: kr-proxy
 * 한국 전용 사이트 프록시 - Cloudflare Seoul POP 활용
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

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method !== "POST") {
      return Response.json({ error: "POST만 허용" }, { status: 405, headers: CORS_HEADERS });
    }

    // 인증: SECRET_KEY 환경변수로 검증
    const authHeader = request.headers.get("authorization") || "";
    const token = authHeader.replace("Bearer ", "");
    if (env.SECRET_KEY && token !== env.SECRET_KEY) {
      return Response.json({ error: "Unauthorized" }, { status: 401, headers: CORS_HEADERS });
    }

    try {
      const body = await request.json();
      const url = body.url;

      if (!url || typeof url !== "string") {
        return Response.json({ error: "url 필수" }, { status: 400, headers: CORS_HEADERS });
      }

      let parsedUrl;
      try {
        parsedUrl = new URL(url);
      } catch {
        return Response.json({ error: "잘못된 URL" }, { status: 400, headers: CORS_HEADERS });
      }

      const hostname = parsedUrl.hostname.toLowerCase();
      if (!ALLOWED_DOMAINS.some(d => hostname === d || hostname.endsWith(`.${d}`))) {
        return Response.json(
          { error: `허용되지 않은 도메인: ${hostname}` },
          { status: 403, headers: CORS_HEADERS }
        );
      }

      const response = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

      // EUC-KR 인코딩 처리
      let html;
      if (contentType.includes("euc-kr") || contentType.includes("euc_kr")) {
        html = new TextDecoder("euc-kr").decode(buffer);
      } else {
        html = new TextDecoder("utf-8").decode(buffer);
        if (html.includes("euc-kr") || html.includes("EUC-KR")) {
          html = new TextDecoder("euc-kr").decode(buffer);
        }
      }

      return Response.json(
        { status: response.status, html, content_type: contentType, url: response.url },
        { status: 200, headers: CORS_HEADERS }
      );
    } catch (error) {
      return Response.json(
        { error: error.message || String(error) },
        { status: 500, headers: CORS_HEADERS }
      );
    }
  },
};
