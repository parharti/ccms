"""
Pydantic schemas for candidate upload and listing endpoints.
"""

from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class CandidateDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_type: str
    original_filename: str


class CVCertificationOut(BaseModel):
    """One certification/course/licence the candidate lists in their CV,
    as extracted by Gemini during screening."""

    name: str
    issuer: Optional[str] = None
    year: Optional[str] = None
    is_cyber_security: bool = False
    reason: Optional[str] = None


class ConsistencyCheckOut(BaseModel):
    """One roster-vs-resume comparison (experience or a must-have item)."""

    item: str
    roster: Optional[str] = None
    resume: Optional[str] = None
    verdict: str  # consistent / inconsistent / unverified
    note: Optional[str] = None


class ResumeConsistencyOut(BaseModel):
    overall: str  # consistent / inconsistent / unverified
    checks: List[ConsistencyCheckOut] = []


class GovJobOut(BaseModel):
    """One job from the Government Relevant Experience check."""

    organisation: str
    designation: Optional[str] = None
    period: Optional[str] = None
    is_government: bool = False
    role_relevant: bool = False
    reason: Optional[str] = None


class GovExperienceOut(BaseModel):
    jobs: List[GovJobOut] = []


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    raw_category: Optional[str] = None
    normalized_category: Optional[str] = None
    ingestion_status: str
    # Roster-only uploads: whether the resume link has been fetched yet
    # (no_link / pending / fetching / fetched / failed). None for ZIP uploads.
    resume_fetch_status: Optional[str] = None
    resume_fetch_error: Optional[str] = None
    # Why a needs-review candidate is there (strong_exception /
    # awaiting_resume / resume_unavailable) and the human-readable detail.
    review_tag: Optional[str] = None
    review_note: Optional[str] = None
    # 0-100 weighted score over the soft sections; the ranking sorts by it.
    suitability_score: Optional[int] = None
    computed_status: Optional[str] = None
    status: str
    status_overridden: bool = False
    last_screening_run_id: Optional[str] = None
    # True = the result was produced under criteria that have since been
    # edited, so it needs a re-screen; None = not screened yet. Set only by
    # the candidates-list endpoint.
    results_outdated: Optional[bool] = None
    # None = not extracted yet (not screened, or no readable CV); [] = the
    # CV lists no certifications.
    cv_certifications: Optional[List[CVCertificationOut]] = None
    has_cyber_security_certification: Optional[bool] = None
    # Roster-vs-resume check on experience + must-haves; None = not checked.
    resume_consistency: Optional[ResumeConsistencyOut] = None
    # Government Relevant Experience: gov_tag is what's shown and ranked on
    # (never on a not-eligible candidate); gov_experience lists every job.
    gov_tag: bool = False
    gov_experience: Optional[GovExperienceOut] = None
    # Overall skills-match % from the screening's skill criterion; None
    # until screened (or when the post has no skill criterion).
    skill_match_percentage: Optional[int] = None
    documents: List[CandidateDocumentOut] = []


class CandidateUploadSummary(BaseModel):
    job_profile_id: str
    total_candidates_found: int
    # How many of those replaced an existing candidate (matched by the
    # Excel "Id." column) instead of being newly created.
    replaced_candidates: int = 0
    documents_complete: int
    documents_incomplete: int
    no_documents_found: int
    excel_row_not_found: int
    corrupt_zip: int
    candidates: List[CandidateOut]
