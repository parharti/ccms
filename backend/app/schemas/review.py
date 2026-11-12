"""
Pydantic schemas for the Manual Review endpoints -- the full
criterion-by-criterion breakdown for a candidate, plus HR's ability to
override the final status.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.candidate import CVCertificationOut, ResumeConsistencyOut, GovExperienceOut

ALLOWED_OVERRIDE_STATUSES = {"eligible", "not_eligible", "needs_review"}


class SkillMarkOut(BaseModel):
    """How one JD skill was marked: level (same / related / none) x HR's weight."""

    skill: str
    weight: float
    level: str
    candidate_skill: Optional[str] = None
    source: Optional[str] = None
    mark: float
    points: float
    reason: Optional[str] = None


class CriterionEvaluationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion_id: str
    criterion_type: str
    criterion_description: str
    is_essential: bool
    result: str
    match_percentage: Optional[int] = None
    skill_marks: Optional[List["SkillMarkOut"]] = None
    citation_document: Optional[str] = None
    citation_page: Optional[int] = None
    reasoning: Optional[str] = None


class ReviewDocumentOut(BaseModel):
    """One uploaded document, so the frontend can turn citation names in
    the criterion breakdown into links that open the actual file."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_type: str
    original_filename: str


class CandidateReviewDetail(BaseModel):
    candidate_id: str
    external_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    ingestion_status: str
    computed_status: Optional[str] = None
    status: str
    status_overridden: bool
    override_reason: Optional[str] = None
    overridden_by: Optional[str] = None
    overridden_at: Optional[datetime] = None
    cv_certifications: Optional[List[CVCertificationOut]] = None
    has_cyber_security_certification: Optional[bool] = None
    resume_consistency: Optional[ResumeConsistencyOut] = None
    review_tag: Optional[str] = None
    review_note: Optional[str] = None
    suitability_score: Optional[int] = None
    gov_tag: bool = False
    gov_experience: Optional[GovExperienceOut] = None
    evaluations: List[CriterionEvaluationDetail] = []
    documents: List[ReviewDocumentOut] = []


class OverrideRequest(BaseModel):
    new_status: str
    reason: Optional[str] = None

    @field_validator("new_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ALLOWED_OVERRIDE_STATUSES:
            raise ValueError(
                f"new_status must be one of {sorted(ALLOWED_OVERRIDE_STATUSES)}, got '{v}'"
            )
        return v


class OverrideResponse(BaseModel):
    candidate_id: str
    status: str
    status_overridden: bool
    override_reason: Optional[str] = None
    overridden_by: Optional[str] = None
    overridden_at: Optional[datetime] = None
