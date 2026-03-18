/**
 * Auth 유틸리티 테스트
 */
import { describe, it, expect } from 'vitest';

describe('Auth Module', () => {
  it('Supabase 환경변수 키 형식이 올바름', () => {
    // 환경변수 키 형식 검증 (실제 값은 테스트 환경에 없을 수 있음)
    const validUrlPattern = /^https?:\/\//;
    const testUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || 'https://example.supabase.co';
    expect(testUrl).toMatch(validUrlPattern);
  });
});
