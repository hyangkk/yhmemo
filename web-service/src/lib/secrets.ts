import { getServiceSupabase } from "./supabase";

// 인메모리 캐시 (1시간 TTL)
const secretsCache: Record<string, { value: string; timestamp: number }> = {};
const CACHE_TTL = 60 * 60 * 1000;

/**
 * 환경변수에서 먼저 찾고, 없으면 Supabase secrets_vault에서 가져옴
 */
export async function getSecret(key: string): Promise<string | undefined> {
  // 1. 환경변수 우선
  const envValue = process.env[key];
  if (envValue) return envValue;

  // 2. 캐시 확인
  const cached = secretsCache[key];
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.value;
  }

  // 3. Supabase secrets_vault에서 조회
  try {
    const supabase = getServiceSupabase();
    const { data, error } = await supabase
      .from("secrets_vault")
      .select("value")
      .eq("key", key)
      .single();

    if (error || !data?.value) {
      console.error(`Secret ${key} not found in secrets_vault:`, error?.message);
      return undefined;
    }

    secretsCache[key] = { value: data.value, timestamp: Date.now() };
    return data.value;
  } catch (err) {
    console.error(`Failed to fetch secret ${key}:`, err);
    return undefined;
  }
}
