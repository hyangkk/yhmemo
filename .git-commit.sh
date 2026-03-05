#!/bin/bash
set -e
cd /home/user/yhmemo
git add webapp/models.py webapp/database.py webapp/crawler.py webapp/matcher.py webapp/main.py webapp/requirements.txt
git rm --cached webapp/hello.py 2>/dev/null || true
git rm webapp/hello.py 2>/dev/null || true
git commit -m "feat: GrantMatch K-Startup 지원금 자동 매칭 SaaS MVP 구축

- models.py: Grant, CompanyProfile, MatchResult Pydantic 모델
- database.py: Supabase 연동 (upsert/fetch)
- crawler.py: K-Startup 공고 크롤러 + 샘플 데이터 5건
- matcher.py: 창업단계·업종·마감일·지원금액 기반 매칭 스코어링
- main.py: FastAPI 앱 (GET /grants, POST /match, GET /health)
- requirements.txt: 의존성 패키지 정의
- hello.py 삭제

https://claude.ai/code/session_01HaXmg7QwLhqQYY2C4PHSzp"
git push origin HEAD
