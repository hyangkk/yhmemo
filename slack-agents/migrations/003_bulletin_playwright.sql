-- bulletin_boards 테이블에 use_playwright 컬럼 추가
ALTER TABLE bulletin_boards ADD COLUMN IF NOT EXISTS use_playwright BOOLEAN DEFAULT FALSE;

-- bulletin_posts 테이블에 content(본문) 컬럼 추가
ALTER TABLE bulletin_posts ADD COLUMN IF NOT EXISTS content TEXT DEFAULT '';

-- yicare.or.kr 용인시육아종합지원센터 게시판 등록
INSERT INTO bulletin_boards (name, url, parser_type, use_playwright, active)
VALUES (
    '용인시육아종합지원센터',
    'https://www.yicare.or.kr/main/main.php?categoryid=25&menuid=01&groupid=00',
    'auto',
    TRUE,
    TRUE
)
ON CONFLICT DO NOTHING;
