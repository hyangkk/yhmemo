#!/usr/bin/env python3
"""
게시판 스크래퍼용 Supabase 테이블 생성 스크립트

실행: python scripts/create_bulletin_tables.py
환경변수: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import os
import json
import urllib.request
import urllib.error

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def table_exists(table_name: str) -> bool:
    """REST API로 테이블 존재 여부 확인"""
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table_name}?select=id&limit=1",
        headers=headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404 or b"PGRST" in e.read():
            return False
        return False


def create_tables_via_rpc():
    """Supabase에 DDL을 실행할 수 있는 RPC가 없으므로,
    REST API의 insert를 통해 테이블 존재를 확인하고 안내 메시지 출력"""

    if table_exists("bulletin_boards"):
        print("✅ bulletin_boards 테이블이 이미 존재합니다.")
    else:
        print("❌ bulletin_boards 테이블이 없습니다.")
        print("   Supabase Dashboard → SQL Editor에서 다음 SQL을 실행하세요:")
        print()
        print("""
CREATE TABLE IF NOT EXISTS bulletin_boards (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    parser_type TEXT DEFAULT 'auto',
    css_selector TEXT DEFAULT '',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bulletin_posts (
    id BIGSERIAL PRIMARY KEY,
    board_id BIGINT REFERENCES bulletin_boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    url TEXT DEFAULT '',
    post_date TEXT DEFAULT '',
    hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bulletin_posts_hash ON bulletin_posts(hash);
CREATE INDEX IF NOT EXISTS idx_bulletin_posts_board_id ON bulletin_posts(board_id);
CREATE INDEX IF NOT EXISTS idx_bulletin_boards_active ON bulletin_boards(active);

-- 첫 번째 게시판: 용인시육아종합지원센터
INSERT INTO bulletin_boards (name, url, parser_type)
VALUES ('용인시육아센터', 'https://www.yicare.or.kr/main/main.php?categoryid=25&menuid=01&groupid=00', 'auto');
""")
        return False

    if table_exists("bulletin_posts"):
        print("✅ bulletin_posts 테이블이 이미 존재합니다.")
    else:
        print("❌ bulletin_posts 테이블이 없습니다. (위 SQL 실행 필요)")
        return False

    # 용인시육아센터 게시판이 등록되어 있는지 확인
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/bulletin_boards?select=id,name&name=eq.용인시육아센터",
        headers=headers(),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data:
                print(f"✅ 용인시육아센터 게시판 등록됨 (id={data[0]['id']})")
            else:
                # 자동 등록
                insert_req = urllib.request.Request(
                    f"{SUPABASE_URL}/rest/v1/bulletin_boards",
                    data=json.dumps({
                        "name": "용인시육아센터",
                        "url": "https://www.yicare.or.kr/main/main.php?categoryid=25&menuid=01&groupid=00",
                        "parser_type": "auto",
                        "active": True,
                    }).encode("utf-8"),
                    headers=headers(),
                    method="POST",
                )
                with urllib.request.urlopen(insert_req, timeout=10):
                    print("✅ 용인시육아센터 게시판 자동 등록 완료")
    except Exception as e:
        print(f"⚠️ 게시판 등록 확인 실패: {e}")

    return True


if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 환경변수를 설정하세요.")
        exit(1)

    print("=== 게시판 스크래퍼 Supabase 테이블 확인 ===\n")
    create_tables_via_rpc()
