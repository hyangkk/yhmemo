import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';

// GET: 세션 상세 정보 (디바이스, 클립 포함)
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = getServiceSupabase();

  const [sessionRes, devicesRes, clipsRes, resultsRes] = await Promise.all([
    supabase.from('studio_sessions').select('*').eq('id', id).single(),
    supabase.from('studio_devices').select('*').eq('session_id', id).order('camera_index'),
    supabase.from('studio_clips').select('*').eq('session_id', id),
    supabase.from('studio_results').select('*').eq('session_id', id).order('created_at', { ascending: false }).limit(1),
  ]);

  if (sessionRes.error) {
    return NextResponse.json({ error: '세션을 찾을 수 없습니다' }, { status: 404 });
  }

  return NextResponse.json({
    session: sessionRes.data,
    devices: devicesRes.data || [],
    clips: clipsRes.data || [],
    result: resultsRes.data?.[0] || null,
  });
}

// PATCH: 세션 상태 업데이트
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json();
  const supabase = getServiceSupabase();

  const { data, error } = await supabase
    .from('studio_sessions')
    .update({ ...body, updated_at: new Date().toISOString() })
    .eq('id', id)
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
