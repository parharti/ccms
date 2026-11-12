"""
Pydantic schemas for the screening/evaluation endpoints.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.schemas.candidate import CVCertificationOut, ResumeConsistencyOut


class CriterionEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    criterion_id: str
    result: str
    match_percentage: Optional[int] = None
    citation_document: Optional[str] = None
    citation_page: Optional[int] = None
    reasoning: Optional[str] = None


class CandidateEvaluationResult(BaseModel):
    candidate_id: str
    ingestion_status: str
    status: str
    skipped: bool = False
    skip_reason: Optional[str] = None
    cv_certifications: Optional[List[CVCertificationOut]] = None
    has_cyber_security_certification: Optional[bool] = None
    resume_consistency: Optional[ResumeConsistencyOut] = None
    evaluations: List[CriterionEvaluationOut] = []


class ScreeningRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_profile_id: str
    total_candidates: int
    processed_count: int
    failed_count: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    # How many candidates CURRENTLY belong to this run (their latest
    # screening). Set only by the runs-list endpoint; differs from
    # total_candidates once some of the run's candidates are re-screened
    # in a later run or deleted.
    current_candidates: Optional[int] = None
    # Stopped/crashed runs only: how many of the run's candidates it never
    # reached (what "Continue" would screen). None = nothing to continue.
    remaining_candidates: Optional[int] = None
