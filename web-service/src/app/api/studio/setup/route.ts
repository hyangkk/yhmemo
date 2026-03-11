import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// POST: DB 마이그레이션 + Storage 버킷 셋업 (배포 후 1회 호출)
export async function POST(req: NextRequest) {
  // 간단한 시크릿 체크
  const { secret } = await req.json().catch(() => ({ secret: '' }));
  if (secret !== process.env.SUPABASE_SERVICE_ROLE_KEY) {
    return NextResponse.json({ error: '인증 실패' }, { status: 401 });
  }

  const supabase = getServiceSupabase();
  const results: string[] = [];

  // 1. 테이블 생성 (SQL via rpc)
  // Supabase REST API로는 직접 DDL 실행 불가 → 테이블이 없으면 insert 시도로 확인
  const { error: checkErr } = await supabase
    .from('studio_sessions')
    .select('id')
    .limit(1);

  if (checkErr?.code === 'PGRST205') {
    results.push('studio 테이블이 없습니다. Supabase Dashboard > SQL Editor에서 마이그레이션을 실행해주세요.');
  } else {
    results.push('studio 테이블 존재 확인됨');
  }

  // 2. Storage 버킷 생성
  const { data: buckets } = await supabase.storage.listBuckets();
  const bucketExists = buckets?.some(b => b.name === 'studio-clips');

  if (!bucketExists) {
    const { error: bucketErr } = await supabase.storage.createBucket('studio-clips', {
      public: true,
      fileSizeLimit: 500 * 1024 * 1024, // 500MB
      allowedMimeTypes: ['video/*', 'audio/*'],
    });

    if (bucketErr) {
      results.push(`Storage 버킷 생성 실패: ${bucketErr.message}`);
    } else {
      results.push('Storage 버킷 studio-clips 생성 완료');
    }
  } else {
    results.push('Storage 버킷 studio-clips 이미 존재');
  }

  return NextResponse.json({ results });
}
