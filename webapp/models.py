from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


class Grant(BaseModel):
    id: Optional[str] = None
    title: str
    organization: str
    category: str
    description: str
    max_amount: Optional[int] = None
    deadline: Optional[date] = None
    target_stage: List[str] = Field(default_factory=list)
    target_industry: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    created_at: Optional[str] = None


class CompanyProfile(BaseModel):
    name: str
    industry: str
    stage: str  # 예: "예비창업", "초기창업", "도약기", "성장기"
    employees: Optional[int] = None
    revenue: Optional[int] = None  # 단위: 만원
    founded_year: Optional[int] = None
    keywords: List[str] = Field(default_factory=list)
    location: Optional[str] = None


class MatchResult(BaseModel):
    grant: Grant
    score: float
    reasons: List[str]


class MatchResponse(BaseModel):
    company: CompanyProfile
    matches: List[MatchResult]
    total: int
