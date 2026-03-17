/**
 * Cloudflare Worker: kr-proxy
 * 한국 전용 사이트 프록시 - X-Forwarded-For 한국 IP 스푸핑으로 WAF 우회
 */

const ALLOWED_DOMAINS = [
  "yicare.or.kr",
  "www.yicare.or.kr",
  "gcm.ggcf.kr",
  "www.yongin.go.kr",
  "eminwon.yongin.go.kr",
];

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, content-type",
};

addEventListener("fetch", function(event) {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  if (request.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  if (request.method === "GET") {
    return new Response(JSON.stringify({status: "ok", service: "kr-proxy"}), {
      headers: {"Content-Type": "application/json"}
    });
  }

  if (request.method !== "POST") {
    return new Response(JSON.stringify({ error: "POST만 허용" }), {
      status: 405,
      headers: Object.assign({"Content-Type": "application/json"}, CORS_HEADERS)
    });
  }

  try {
    var body = await request.json();
    var url = body.url;

    if (!url || typeof url !== "string") {
      return new Response(JSON.stringify({ error: "url 필수" }), {
        status: 400,
        headers: Object.assign({"Content-Type": "application/json"}, CORS_HEADERS)
      });
    }

    var parsedUrl;
    try {
      parsedUrl = new URL(url);
    } catch (e) {
      return new Response(JSON.stringify({ error: "잘못된 URL" }), {
        status: 400,
        headers: Object.assign({"Content-Type": "application/json"}, CORS_HEADERS)
      });
    }

    var hostname = parsedUrl.hostname.toLowerCase();
    var allowed = ALLOWED_DOMAINS.some(function(d) {
      return hostname === d || hostname.endsWith("." + d);
    });
    if (!allowed) {
      return new Response(JSON.stringify({ error: "허용되지 않은 도메인: " + hostname }), {
        status: 403,
        headers: Object.assign({"Content-Type": "application/json"}, CORS_HEADERS)
      });
    }

    var headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
      "Cache-Control": "max-age=0",
      "Connection": "keep-alive",
      "Upgrade-Insecure-Requests": "1",
    };

    // X-Forwarded-For 한국 IP 스푸핑 (WAF 우회)
    if (body.spoof_ip) {
      headers["X-Forwarded-For"] = body.spoof_ip;
      headers["X-Real-IP"] = body.spoof_ip;
      headers["True-Client-IP"] = body.spoof_ip;
    }

    if (body.cookie) {
      headers["Cookie"] = body.cookie;
    }
    if (body.referer) {
      headers["Referer"] = body.referer;
    }

    var resp = await fetch(url, {
      headers: headers,
      redirect: "follow",
    });

    var buffer = await resp.arrayBuffer();
    var bytes = new Uint8Array(buffer);
    var ct = resp.headers.get("content-type") || "";

    // 바이너리 콘텐츠(이미지 등)는 base64로 반환
    if (/^(image|audio|video|application\/octet|application\/pdf)/i.test(ct)) {
      var binary = "";
      for (var i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
      }
      var base64 = btoa(binary);
      return new Response(JSON.stringify({
        status: resp.status,
        base64: base64,
        content_type: ct,
        url: resp.url || url,
      }), {
        status: 200,
        headers: Object.assign({"Content-Type": "application/json; charset=utf-8"}, CORS_HEADERS)
      });
    }

    // 인코딩 감지 및 디코딩 (EUC-KR 한국 사이트 대응)
    var html = "";
    if (ct.toLowerCase().indexOf("euc-kr") >= 0 || ct.toLowerCase().indexOf("cp949") >= 0) {
      html = new TextDecoder("euc-kr").decode(bytes);
    } else {
      var preview = new TextDecoder("ascii", {fatal: false}).decode(bytes.slice(0, 2000));
      var charsetMatch = preview.match(/charset=["']?(euc-kr|EUC-KR|cp949)/i);
      if (charsetMatch) {
        html = new TextDecoder("euc-kr").decode(bytes);
      } else {
        try {
          html = new TextDecoder("utf-8", {fatal: true}).decode(bytes);
        } catch (e) {
          html = new TextDecoder("euc-kr").decode(bytes);
        }
      }
    }

    return new Response(JSON.stringify({
      status: resp.status,
      html: html,
      content_type: ct,
      url: resp.url || url,
    }), {
      status: 200,
      headers: Object.assign({"Content-Type": "application/json; charset=utf-8"}, CORS_HEADERS)
    });
  } catch (error) {
    return new Response(JSON.stringify({ error: error.message || String(error) }), {
      status: 500,
      headers: Object.assign({"Content-Type": "application/json"}, CORS_HEADERS)
    });
  }
}
