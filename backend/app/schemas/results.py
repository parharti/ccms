"""
Pydantic schemas for the results/export endpoints.
"""

from typing import List
from pydantic import BaseModel

from app.schemas.candidate import CandidateOut


class ResultsSummary(BaseModel):
    total: int
    eligible: int
    # needs-review candidates tagged strong_exception, counted on their own
    # (and NOT in needs_review)
    eligible_with_exception: int = 0
    not_eligible: int
    needs_review: int
    not_evaluated: int
    gov_tagged: int = 0


class ResultsResponse(BaseModel):
    summary: ResultsSummary
    candidates: List[CandidateOut]
