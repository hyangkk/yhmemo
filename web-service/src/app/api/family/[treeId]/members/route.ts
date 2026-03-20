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

// POST: 구성원 추가
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();
  const { name, gender, birth_date, is_lunar_birth, death_date, is_deceased, bio, photo_url } = body;

  if (!name || !gender) {
    return NextResponse.json({ error: '이름과 성별은 필수입니다' }, { status: 400 });
  }

  const sb = getServiceSupabase();

  // 가계도 소유자 확인
  const { data: tree } = await sb
    .from('family_trees')
    .select('id')
    .eq('id', treeId)
    .eq('user_id', user.id)
    .single();

  if (!tree) return NextResponse.json({ error: '가계도를 찾을 수 없습니다' }, { status: 404 });

  const { data: member, error } = await sb
    .from('family_members')
    .insert({
      tree_id: treeId,
      name,
      gender,
      birth_date: birth_date || null,
      is_lunar_birth: is_lunar_birth || false,
      death_date: death_date || null,
      is_deceased: is_deceased || false,
      bio: bio || null,
      photo_url: photo_url || null,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ member }, { status: 201 });
}

// PUT: 구성원 수정
export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ treeId: string }> }
) {
  const user = await getUser(req);
  if (!user) return NextResponse.json({ error: '인증 필요' }, { status: 401 });

  const { treeId } = await params;
  const body = await req.json();
  const { id, ...updates } = body;

  if (!id) return NextResponse.json({ error: '구성원 ID가 필요합니다' }, { status: 400 });

  const sb = getServiceSupabase();

  const { data: member, error } = await sb
    .from('family_members')
    .update(updates)
    .eq('id', id)
    .eq('tree_id', treeId)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ member });
}
