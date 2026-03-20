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

// POST: 이벤트 추가 (생일, 기일, 명절 일지 등)
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();

  const sb = getServiceSupabase();
  const { data: event, error } = await sb
    .from('family_events')
    .insert({
      tree_id: treeId,
      member_id: body.member_id || null,
      event_type: body.event_type,
      title: body.title,
      date: body.date,
      is_lunar: body.is_lunar || false,
      description: body.description || null,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ event }, { status: 201 });
}

// PUT: 이벤트 수정
export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();
  const { id, ...updates } = body;

  const sb = getServiceSupabase();
  const { data: event, error } = await sb
    .from('family_events')
    .update(updates)
    .eq('id', id)
    .eq('tree_id', treeId)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ event });
}
