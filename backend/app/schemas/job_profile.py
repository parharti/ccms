"""
Pydantic schemas -- these define the shape of the API responses.
Kept separate from the SQLAlchemy models so the DB structure and the API
contract can evolve independently.
"""

from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class SkillItem(BaseModel):
    """One JD skill marked on its own; weight is 1, 0.5 or 0."""
    name: str
    weight: float = 1.0


class CriterionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    description: str
    is_essential: bool
    display_order: int
    required_match_percentage: Optional[int] = None
    # Skill criteria only: the skills marked one by one, with HR's weights.
    skill_items: Optional[List[SkillItem]] = Field(default=None, validation_alias="skill_items_effective")
    # Skill criteria only: the mark (0-1) a related skill earns.
    related_mark: Optional[float] = Field(default=None, validation_alias="related_mark_effective")


class AgeRelaxationRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_category: str
    normalized_category: str
    relaxation_text: str


class JobProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    method_of_recruitment: Optional[str] = None
    pay_scale: Optional[str] = None
    base_age_min: Optional[int] = None
    base_age_max: Optional[int] = None
    experience_tolerance_years: float = 2.0
    exception_skills_threshold: int = 80
    weight_skills: int = 70
    weight_experience: int = 30  # unused, see JobProfile.weight_experience
    weight_desirable: int = 30
    close_miss_skills_min: Optional[int] = None
    close_miss_experience_min: Optional[int] = None
    close_miss_desirable_min: Optional[int] = None
    rank_by_suitability: bool = True
    criteria: List[CriterionOut] = []
    age_relaxation_rules: List[AgeRelaxationRuleOut] = []


class JDUploadResponse(BaseModel):
    jd_upload_id: str
    filename: str
    parse_confidence: str
    ambiguity_notes: str
    post_count: int
    validation_warnings: List[str] = []
    is_duplicate: bool = False
    duplicate_message: Optional[str] = None
    job_profiles: List[JobProfileOut]


# ---- Criteria Editor request schemas ----

class CriterionCreate(BaseModel):
    type: str  # education / experience / skill / age / other
    description: str
    is_essential: bool = True
    display_order: Optional[int] = None  # None -> appended to the end of the list
    # Skill criteria only: minimum match % required when essential.
    required_match_percentage: Optional[int] = None
    # Skill criteria only: the skills with weights; None = split the description.
    skill_items: Optional[List[SkillItem]] = None
    # Skill criteria only: the mark (0-1) a related skill earns; None = 0.5.
    related_mark: Optional[float] = Field(default=None, ge=0, le=1)


class CriterionUpdate(BaseModel):
    """All fields are optional -- only the fields you send get updated (partial update)."""
    type: Optional[str] = None
    description: Optional[str] = None
    is_essential: Optional[bool] = None
    display_order: Optional[int] = None
    required_match_percentage: Optional[int] = None
    skill_items: Optional[List[SkillItem]] = None
    related_mark: Optional[float] = Field(default=None, ge=0, le=1)


class ProfileSettingsUpdate(BaseModel):
    """Partial update of a post's screening settings."""
    experience_tolerance_years: Optional[float] = None
    exception_skills_threshold: Optional[int] = None
    weight_skills: Optional[int] = None
    weight_experience: Optional[int] = None
    weight_desirable: Optional[int] = None
    # Explicitly sending null switches a close-miss section off.
    close_miss_skills_min: Optional[int] = None
    close_miss_experience_min: Optional[int] = None
    close_miss_desirable_min: Optional[int] = None
    rank_by_suitability: Optional[bool] = None


class CriteriaRestoreResponse(BaseModel):
    restored_count: int
    profile: JobProfileOut
