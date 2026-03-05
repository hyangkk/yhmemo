import logging
import os
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from models import CompanyProfile, Grant, MatchResponse
from matcher import match_grants
from crawler import crawl_kstartup, get_sample_grants

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="GrantMatch - K-Startup 지원금 자동 매칭",
    description="K-Startup 공고를 크롤링하고 회사 프로필에 맞는 지원금을 자동으로 매칭합니다.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USE_DB = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))

_grants_cache: List[Grant] = []


def _load_grants() -> List[Grant]:
    global _grants_cache
    if _grants_cache:
        return _grants_cache

    if USE_DB:
        try:
            from database import fetch_grants
            _grants_cache = fetch_grants(limit=500)
            logger.info(f"DB에서 {len(_grants_cache)}건 로드")
        except Exception as e:
            logger.warning(f"DB 로드 실패, 샘플 데이터 사용: {e}")
            _grants_cache = get_sample_grants()
    else:
        _grants_cache = get_sample_grants()

    return _grants_cache


def _refresh_grants():
    global _grants_cache
    try:
        grants = crawl_kstartup(pages=5)
        if not grants:
            logger.warning("크롤링 결과 없음, 샘플 유지")
            return
        if USE_DB:
            from database import upsert_grants
            saved = upsert_grants(grants)
            logger.info(f"DB에 {saved}건 저장")
        _grants_cache = grants
        logger.info(f"지원금 갱신 완료: {len(grants)}건")
    except Exception as e:
        logger.error(f"지원금 갱신 실패: {e}")


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "db_connected": USE_DB,
        "grants_cached": len(_grants_cache),
    }


@app.get("/grants", response_model=List[Grant])
def list_grants(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    stage: Optional[str] = Query(default=None),
    industry: Optional[str] = Query(default=None),
):
    grants = _load_grants()

    if stage:
        grants = [g for g in grants if stage in g.target_stage or "전체" in g.target_stage]
    if industry:
        grants = [g for g in grants if industry in g.target_industry or "전체" in g.target_industry]

    return grants[offset: offset + limit]


@app.post("/match", response_model=MatchResponse)
def match(
    company: CompanyProfile,
    top_k: int = Query(default=5, ge=1, le=20),
):
    grants = _load_grants()
    if not grants:
        raise HTTPException(status_code=503, detail="지원금 데이터를 불러올 수 없습니다.")

    results = match_grants(company, grants, top_k=top_k)
    return MatchResponse(company=company, matches=results, total=len(results))


@app.post("/grants/refresh")
def refresh_grants(background_tasks: BackgroundTasks):
    background_tasks.add_task(_refresh_grants)
    return {"message": "지원금 데이터 갱신을 백그라운드에서 시작했습니다."}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
