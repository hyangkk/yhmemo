from typing import List

from models import CompanyProfile, Grant, MatchResult


STAGE_COMPATIBILITY: dict[str, List[str]] = {
    "예비창업": ["예비창업", "전체"],
    "초기창업": ["초기창업", "전체"],
    "도약기": ["도약기", "전체"],
    "성장기": ["성장기", "도약기", "전체"],
}


def _score_stage(company: CompanyProfile, grant: Grant) -> tuple[float, List[str]]:
    compatible = STAGE_COMPATIBILITY.get(company.stage, ["전체"])
    if not grant.target_stage:
        return 0.2, []
    if any(s in compatible for s in grant.target_stage):
        return 0.4, [f"창업 단계 적합 ({company.stage})"]
    return 0.0, []


def _score_industry(company: CompanyProfile, grant: Grant) -> tuple[float, List[str]]:
    if not grant.target_industry or "전체" in grant.target_industry:
        return 0.2, ["업종 제한 없음"]

    company_terms = set([company.industry] + company.keywords)
    matched = [ind for ind in grant.target_industry if ind in company_terms]
    if matched:
        score = min(0.4, 0.2 * len(matched))
        return score, [f"업종 매칭: {', '.join(matched)}"]
    return 0.0, []


def _score_deadline(grant: Grant) -> tuple[float, List[str]]:
    if grant.deadline is None:
        return 0.1, []
    from datetime import date
    today = date.today()
    delta = (grant.deadline - today).days
    if delta < 0:
        return 0.0, ["마감된 공고"]
    if delta <= 14:
        return 0.15, [f"마감 임박 ({delta}일 남음)"]
    return 0.2, [f"마감까지 {delta}일"]


def _score_amount(company: CompanyProfile, grant: Grant) -> tuple[float, List[str]]:
    if grant.max_amount is None:
        return 0.0, []
    if grant.max_amount >= 10000:
        return 0.1, [f"최대 {grant.max_amount // 10000}억원 지원"]
    return 0.05, [f"최대 {grant.max_amount}만원 지원"]


def match_grants(
    company: CompanyProfile,
    grants: List[Grant],
    top_k: int = 10,
    min_score: float = 0.2,
) -> List[MatchResult]:
    results: List[MatchResult] = []

    for grant in grants:
        score = 0.0
        reasons: List[str] = []

        stage_score, stage_reasons = _score_stage(company, grant)
        score += stage_score
        reasons.extend(stage_reasons)

        industry_score, industry_reasons = _score_industry(company, grant)
        score += industry_score
        reasons.extend(industry_reasons)

        deadline_score, deadline_reasons = _score_deadline(grant)
        score += deadline_score
        reasons.extend(deadline_reasons)

        amount_score, amount_reasons = _score_amount(company, grant)
        score += amount_score
        reasons.extend(amount_reasons)

        if score >= min_score and reasons:
            results.append(
                MatchResult(grant=grant, score=round(score, 3), reasons=reasons)
            )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
