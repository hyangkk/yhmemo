"""한국 프록시 서버 - Fly.io 서울(ICN) 리전 배포용"""
import json
import http.server
import http.cookiejar
import ssl
import urllib.request
import re
import os

PORT = int(os.environ.get("PORT", 8080))
AUTH_KEY = os.environ.get("AUTH_KEY", "")

# 허용 도메인
ALLOWED_DOMAINS = {"yicare.or.kr", "www.yicare.or.kr"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def fetch_url(url: str) -> tuple[int, str]:
    """URL 가져오기 (쿠키 + 리다이렉트 처리)"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx),
    )

    def make_req(target, referer=""):
        req = urllib.request.Request(target)
        for k, v in HEADERS.items():
            req.add_header(k, v)
        if referer:
            req.add_header("Referer", referer)
        return req

    # 1차: 메인 페이지로 쿠키 획득
    try:
        opener.open(make_req(root_url), timeout=10).read()
    except Exception:
        pass

    # 2차: 타겟 URL 접근
    try:
        resp = opener.open(make_req(url, referer=root_url), timeout=20)
        raw = resp.read()
        headers = dict(resp.headers)

        # 인코딩 감지
        ct = headers.get("Content-Type", "")
        charset_m = re.search(r"charset=([^\s;]+)", ct, re.I)
        if charset_m:
            try:
                return resp.status, raw.decode(charset_m.group(1))
            except (UnicodeDecodeError, LookupError):
                pass

        meta_m = re.search(rb'charset=["\']?([^"\'\s;>]+)', raw, re.I)
        if meta_m:
            try:
                return resp.status, raw.decode(meta_m.group(1).decode("ascii", "ignore"))
            except (UnicodeDecodeError, LookupError):
                pass

        for enc in ["utf-8", "euc-kr", "cp949"]:
            try:
                return resp.status, raw.decode(enc)
            except UnicodeDecodeError:
                continue

        return resp.status, raw.decode("utf-8", errors="replace")

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass
        return e.code, body


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        """헬스체크용"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "region": "icn"}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # 인증 확인
        if AUTH_KEY:
            auth = self.headers.get("Authorization", "")
            token = auth.replace("Bearer ", "")
            if token != AUTH_KEY:
                self._json_response(401, {"error": "Unauthorized"})
                return

        try:
            data = json.loads(body)
        except Exception:
            self._json_response(400, {"error": "잘못된 JSON"})
            return

        url = data.get("url", "")
        if not url:
            self._json_response(400, {"error": "url 필수"})
            return

        # 도메인 검사
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        if not any(hostname == d or hostname.endswith(f".{d}") for d in ALLOWED_DOMAINS):
            self._json_response(403, {"error": f"허용되지 않은 도메인: {hostname}"})
            return

        status, html = fetch_url(url)
        self._json_response(200, {"status": status, "html": html, "url": url})

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[kr-proxy] {args[0]}")


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"kr-proxy 서버 시작: 0.0.0.0:{PORT}")
    server.serve_forever()
