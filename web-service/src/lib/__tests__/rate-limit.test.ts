/**
 * Rate Limiting 유틸리티 테스트
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { checkRateLimit, getClientIP, applyRateLimit } from '../rate-limit';

describe('checkRateLimit', () => {
  // 각 테스트마다 고유 IP 사용하여 격리
  let testId: string;

  beforeEach(() => {
    testId = `test-${Date.now()}-${Math.random()}`;
  });

  it('첫 요청은 항상 허용', () => {
    const result = checkRateLimit(testId);
    expect(result.success).toBe(true);
  });

  it('제한 초과 시 차단', () => {
    const config = { maxTokens: 3, refillRate: 0, refillInterval: 60000 };

    // 3번 허용
    expect(checkRateLimit(testId, config).success).toBe(true);
    expect(checkRateLimit(testId, config).success).toBe(true);
    expect(checkRateLimit(testId, config).success).toBe(true);

    // 4번째 차단
    expect(checkRateLimit(testId, config).success).toBe(false);
  });

  it('remaining 카운트가 정확함', () => {
    const config = { maxTokens: 5, refillRate: 0, refillInterval: 60000 };

    const r1 = checkRateLimit(testId, config);
    expect(r1.remaining).toBe(4); // 5 - 1 = 4

    const r2 = checkRateLimit(testId, config);
    expect(r2.remaining).toBe(3);
  });
});

describe('getClientIP', () => {
  it('x-forwarded-for 헤더에서 IP 추출', () => {
    const request = new Request('http://localhost', {
      headers: { 'x-forwarded-for': '1.2.3.4, 5.6.7.8' },
    });
    expect(getClientIP(request)).toBe('1.2.3.4');
  });

  it('x-real-ip 헤더 fallback', () => {
    const request = new Request('http://localhost', {
      headers: { 'x-real-ip': '10.0.0.1' },
    });
    expect(getClientIP(request)).toBe('10.0.0.1');
  });

  it('헤더 없으면 localhost 반환', () => {
    const request = new Request('http://localhost');
    expect(getClientIP(request)).toBe('127.0.0.1');
  });
});

describe('applyRateLimit', () => {
  it('제한 미초과 시 limited=false', () => {
    const request = new Request('http://localhost', {
      headers: { 'x-forwarded-for': `apply-test-${Date.now()}` },
    });
    const result = applyRateLimit(request);
    expect(result.limited).toBe(false);
    expect(result.response).toBeUndefined();
  });

  it('제한 초과 시 429 응답 반환', () => {
    const ip = `blocked-${Date.now()}`;
    const config = { maxTokens: 1, refillRate: 0, refillInterval: 60000 };

    const req1 = new Request('http://localhost', {
      headers: { 'x-forwarded-for': ip },
    });
    applyRateLimit(req1, config); // 1회 소비

    const req2 = new Request('http://localhost', {
      headers: { 'x-forwarded-for': ip },
    });
    const result = applyRateLimit(req2, config);
    expect(result.limited).toBe(true);
    expect(result.response?.status).toBe(429);
  });
});
