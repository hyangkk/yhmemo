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

// POST: 부조/선물 기록 추가
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();

  const sb = getServiceSupabase();
  const { data: entry, error } = await sb
    .from('family_ledger')
    .insert({
      tree_id: treeId,
      event_id: body.event_id || null,
      member_id: body.member_id || null,
      category: body.category,
      direction: body.direction,
      item: body.item || null,
      amount: body.amount || null,
      note: body.note || null,
      date: body.date,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ entry }, { status: 201 });
}

// DELETE: 기록 삭제
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const { searchParams } = new URL(req.url);
  const entryId = searchParams.get('id');

  if (!entryId) return NextResponse.json({ error: 'ID가 필요합니다' }, { status: 400 });

  const sb = getServiceSupabase();
  const { error } = await sb
    .from('family_ledger')
    .delete()
    .eq('id', entryId)
    .eq('tree_id', treeId);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ success: true });
}
