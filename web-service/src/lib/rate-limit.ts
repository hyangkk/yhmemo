/**
 * API Rate Limiting - 토큰 버킷 알고리즘
 *
 * IP 기반으로 요청 횟수를 제한하여 남용/DDoS 방지.
 * 서버리스 환경(Vercel)에서 동작하는 인메모리 방식.
 */

interface RateLimitEntry {
  tokens: number;
  lastRefill: number;
}

interface RateLimitConfig {
  maxTokens: number;      // 최대 토큰 수 (버킷 크기)
  refillRate: number;     // 초당 리필 토큰 수
  refillInterval: number; // 리필 간격 (ms)
}

// 기본 설정: 분당 60회
const DEFAULT_CONFIG: RateLimitConfig = {
  maxTokens: 60,
  refillRate: 1,
  refillInterval: 1000,
};

// 인메모리 저장소 (서버리스 인스턴스 내)
const store = new Map<string, RateLimitEntry>();

// 주기적 클린업 (메모리 누수 방지)
const CLEANUP_INTERVAL = 60_000; // 1분
const ENTRY_TTL = 300_000; // 5분 미사용 시 제거
let lastCleanup = Date.now();

function cleanup() {
  const now = Date.now();
  if (now - lastCleanup < CLEANUP_INTERVAL) return;
  lastCleanup = now;

  for (const [key, entry] of store) {
    if (now - entry.lastRefill > ENTRY_TTL) {
      store.delete(key);
    }
  }
}

/**
 * Rate limit 체크
 * @returns { success: boolean, remaining: number, reset: number }
 */
export function checkRateLimit(
  identifier: string,
  config: Partial<RateLimitConfig> = {}
): { success: boolean; remaining: number; reset: number } {
  cleanup();

  const cfg = { ...DEFAULT_CONFIG, ...config };
  const now = Date.now();

  let entry = store.get(identifier);

  if (!entry) {
    entry = { tokens: cfg.maxTokens - 1, lastRefill: now };
    store.set(identifier, entry);
    return { success: true, remaining: entry.tokens, reset: Math.ceil(cfg.refillInterval / 1000) };
  }

  // 토큰 리필
  const elapsed = now - entry.lastRefill;
  const refillTokens = Math.floor(elapsed / cfg.refillInterval) * cfg.refillRate;

  if (refillTokens > 0) {
    entry.tokens = Math.min(cfg.maxTokens, entry.tokens + refillTokens);
    entry.lastRefill = now;
  }

  // 토큰 소비
  if (entry.tokens > 0) {
    entry.tokens--;
    return { success: true, remaining: entry.tokens, reset: Math.ceil(cfg.refillInterval / 1000) };
  }

  // 제한 초과
  const resetIn = Math.ceil((cfg.refillInterval - (now - entry.lastRefill)) / 1000);
  return { success: false, remaining: 0, reset: Math.max(resetIn, 1) };
}

/**
 * IP 주소 추출 (Vercel 환경 대응)
 */
export function getClientIP(request: Request): string {
  const forwarded = request.headers.get('x-forwarded-for');
  if (forwarded) {
    return forwarded.split(',')[0].trim();
  }
  const realIP = request.headers.get('x-real-ip');
  if (realIP) return realIP;
  return '127.0.0.1';
}

/**
 * Rate limit 미들웨어 헬퍼
 * API route에서 사용:
 *
 * const { limited, response } = applyRateLimit(request);
 * if (limited) return response;
 */
export function applyRateLimit(
  request: Request,
  config?: Partial<RateLimitConfig>
): { limited: boolean; response?: Response } {
  const ip = getClientIP(request);
  const result = checkRateLimit(ip, config);

  if (!result.success) {
    return {
      limited: true,
      response: new Response(
        JSON.stringify({ error: '요청 제한 초과. 잠시 후 다시 시도해주세요.' }),
        {
          status: 429,
          headers: {
            'Content-Type': 'application/json',
            'Retry-After': String(result.reset),
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': String(result.reset),
          },
        }
      ),
    };
  }

  return { limited: false };
}
