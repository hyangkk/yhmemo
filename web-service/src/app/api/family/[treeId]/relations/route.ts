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

// POST: 관계 추가
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();
  const { from_member_id, to_member_id, relation_type } = body;

  if (!from_member_id || !to_member_id || !relation_type) {
    return NextResponse.json({ error: '모든 필드가 필요합니다' }, { status: 400 });
  }

  const sb = getServiceSupabase();

  const { data: relation, error } = await sb
    .from('family_relations')
    .insert({ tree_id: treeId, from_member_id, to_member_id, relation_type })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ relation }, { status: 201 });
}

// DELETE: 관계 삭제
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const { searchParams } = new URL(req.url);
  const relationId = searchParams.get('id');

  if (!relationId) return NextResponse.json({ error: '관계 ID가 필요합니다' }, { status: 400 });

  const sb = getServiceSupabase();

  const { error } = await sb
    .from('family_relations')
    .delete()
    .eq('id', relationId)
    .eq('tree_id', treeId);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ success: true });
}
