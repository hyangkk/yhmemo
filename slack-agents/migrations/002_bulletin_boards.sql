-- 게시판 모니터링 테이블

-- 모니터링 대상 게시판 목록
CREATE TABLE IF NOT EXISTS bulletin_boards (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,                    -- 게시판 이름 (예: "용인시육아센터")
    url TEXT NOT NULL,                     -- 게시판 URL
    parser_type TEXT DEFAULT 'auto',       -- 파서 타입: auto, table, list
    css_selector TEXT DEFAULT '',           -- 커스텀 CSS 선택자 (선택사항)
    active BOOLEAN DEFAULT TRUE,           -- 활성화 여부
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 수집된 게시글
CREATE TABLE IF NOT EXISTS bulletin_posts (
    id BIGSERIAL PRIMARY KEY,
    board_id BIGINT REFERENCES bulletin_boards(id) ON DELETE CASCADE,
    title TEXT NOT NULL,                   -- 게시글 제목
    url TEXT DEFAULT '',                   -- 게시글 URL
    post_date TEXT DEFAULT '',             -- 게시일 (원본 형식 그대로)
    hash TEXT NOT NULL UNIQUE,             -- 중복 체크용 해시
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_bulletin_posts_hash ON bulletin_posts(hash);
CREATE INDEX IF NOT EXISTS idx_bulletin_posts_board_id ON bulletin_posts(board_id);
CREATE INDEX IF NOT EXISTS idx_bulletin_boards_active ON bulletin_boards(active);

-- 첫 번째 게시판 등록: 용인시육아종합지원센터
INSERT INTO bulletin_boards (name, url, parser_type)
VALUES ('용인시육아센터', 'https://www.yicare.or.kr/main/main.php?categoryid=25&menuid=01&groupid=00', 'auto')
ON CONFLICT DO NOTHING;
