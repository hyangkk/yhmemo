import { NextRequest, NextResponse } from 'next/server';
import { getServiceSupabase } from '@/lib/supabase';
import { createClient } from '@supabase/supabase-js';

async function getUser(req: NextRequest) {
  const authHeader = req.headers.get('authorization');
  if (!authHeader) return null;
  const token = authHeader.replace('Bearer ', '');
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
  const { data: { user } } = await supabase.auth.getUser(token);
  return user;
}

// GET: 가계도 상세 (구성원 + 관계 + 이벤트 전부)
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const sb = getServiceSupabase();

  // 가계도 소유자 확인
  const { data: tree } = await sb
    .from('family_trees')
    .select('*')
    .eq('id', treeId)
    .eq('user_id', user.id)
    .single();

  if (!tree) return NextResponse.json({ error: '가계도를 찾을 수 없습니다' }, { status: 404 });

  // 모든 데이터 병렬 조회
  const [membersRes, relationsRes, eventsRes, ledgerRes, memoriesRes] = await Promise.all([
    sb.from('family_members').select('*').eq('tree_id', treeId).order('created_at'),
    sb.from('family_relations').select('*').eq('tree_id', treeId),
    sb.from('family_events').select('*').eq('tree_id', treeId).order('date', { ascending: false }),
    sb.from('family_ledger').select('*').eq('tree_id', treeId).order('date', { ascending: false }),
    sb.from('family_memories').select('*').eq('tree_id', treeId).order('date', { ascending: false }),
  ]);

  return NextResponse.json({
    tree,
    members: membersRes.data || [],
    relations: relationsRes.data || [],
    events: eventsRes.data || [],
    ledger: ledgerRes.data || [],
    memories: memoriesRes.data || [],
  });
}

// DELETE: 가계도 삭제
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const sb = getServiceSupabase();

  const { error } = await sb
    .from('family_trees')
    .delete()
    .eq('id', treeId)
    .eq('user_id', user.id);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ success: true });
}
