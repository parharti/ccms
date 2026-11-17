"""
Models: JDUpload -> JobProfile (one-to-many) -> Criterion, AgeRelaxationRule

One JD upload can produce one or more Job Profiles (in the case of a
multi-post JD). Each Job Profile has its own independent criteria and age
relaxation rules, so HR can edit each profile separately (Criteria Editor
requirement).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Boolean, Integer, Float, ForeignKey, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.services.criteria_utils import normalize_related_mark, normalize_skill_items


def gen_uuid() -> str:
    return str(uuid.uuid4())


class JDUpload(Base):
    __tablename__ = "jd_uploads"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    filename: Mapped[str] = mapped_column(String(500))
    storage_path: Mapped[str] = mapped_column(String(1000))

    # SHA-256 hash of the file's raw bytes -- used to detect whether the
    # exact same file (regardless of filename) has already been uploaded.
    # unique=True so the guarantee also holds at the database level, not
    # just in application logic.
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=True, index=True)

    raw_extracted_text: Mapped[str] = mapped_column(Text, nullable=True)
    # Store Gemini's full raw response here -- useful for debugging and
    # auditing if parsing ever looks wrong later.
    gemini_raw_response: Mapped[dict] = mapped_column(JSON, nullable=True)

    parse_confidence: Mapped[str] = mapped_column(String(20), nullable=True)
    ambiguity_notes: Mapped[str] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job_profiles: Mapped[list["JobProfile"]] = relationship(
        back_populates="source_jd_upload", cascade="all, delete-orphan"
    )


class JobProfile(Base):
    __tablename__ = "job_profiles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    source_jd_upload_id: Mapped[str] = mapped_column(ForeignKey("jd_uploads.id"))

    title: Mapped[str] = mapped_column(String(300))
    method_of_recruitment: Mapped[str] = mapped_column(String(200), nullable=True)
    pay_scale: Mapped[str] = mapped_column(String(200), nullable=True)

    # Base age limit -- parsed (best-effort) from the JD if it stated a
    # clear numeric range. If parsing fails, both stay None -- the raw
    # criterion text will still be shown during screening.
    base_age_min: Mapped[int] = mapped_column(Integer, nullable=True)
    base_age_max: Mapped[int] = mapped_column(Integer, nullable=True)

    # Index into source_jd_upload.gemini_raw_response["posts"] that this
    # profile was created from -- lets the criteria-restore endpoint find
    # the right post's criteria list again later, without relying on a
    # fragile title match (which breaks if HR edits the title, or if two
    # posts in the same JD happen to share a title). Null for profiles
    # created before this tracking was added, or in any future path that
    # doesn't originate from a Gemini parse.
    source_post_index: Mapped[int] = mapped_column(Integer, nullable=True)

    # The department template the candidates for this post were uploaded
    # with (column mapping + evidence mode). NULL = the original IHMCL
    # layout. Deliberately not a ForeignKey: deleting a template must not
    # block or cascade into existing profiles.
    department_template_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=True
    )

    # Screening settings (HR-editable per post). A candidate who misses an
    # essential EXPERIENCE criterion by no more than the tolerance, yet
    # scores at least the skills threshold, is not rejected: they land in
    # "needs review" tagged "strong candidate, with exception".
    experience_tolerance_years: Mapped[float] = mapped_column(Float, default=2.0)
    exception_skills_threshold: Mapped[int] = mapped_column(Integer, default=80)
    # Weights of the suitability score used to rank candidates (any scale;
    # they are normalised over the sections a post actually has). Only
    # skills and desirable items count; weight_experience is kept for old
    # rows but no longer used (experience is handled by the tolerance rule).
    weight_skills: Mapped[int] = mapped_column(Integer, default=70)
    weight_experience: Mapped[int] = mapped_column(Integer, default=30)
    weight_desirable: Mapped[int] = mapped_column(Integer, default=30)
    # "Close miss" tag: a NOT ELIGIBLE candidate who still scores at least
    # this much (0-100) in a section is tagged so HR can look at them. Each
    # section is optional -- NULL switches that section's check off.
    close_miss_skills_min: Mapped[int] = mapped_column(Integer, nullable=True)
    close_miss_experience_min: Mapped[int] = mapped_column(Integer, nullable=True)
    close_miss_desirable_min: Mapped[int] = mapped_column(Integer, nullable=True)
    # Results open ranked by suitability score (best first) when true.
    rank_by_suitability: Mapped[bool] = mapped_column(Boolean, default=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    source_jd_upload: Mapped["JDUpload"] = relationship(back_populates="job_profiles")
    criteria: Mapped[list["Criterion"]] = relationship(
        back_populates="job_profile", cascade="all, delete-orphan",
        order_by="Criterion.display_order",
    )
    age_relaxation_rules: Mapped[list["AgeRelaxationRule"]] = relationship(
        back_populates="job_profile", cascade="all, delete-orphan"
    )


class Criterion(Base):
    __tablename__ = "criteria"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_profile_id: Mapped[str] = mapped_column(ForeignKey("job_profiles.id"))

    type: Mapped[str] = mapped_column(String(50))  # education / experience / skill / age / other
    description: Mapped[str] = mapped_column(Text)
    is_essential: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    # Only meaningful for "skill" criteria that HR marks essential: the
    # minimum skills-match percentage (0-100) a candidate must reach, or
    # they are rejected. NULL = the skill score stays informational.
    required_match_percentage: Mapped[int] = mapped_column(Integer, nullable=True)

    # Only for "skill" criteria: the individual JD skills that are marked
    # one by one, each with HR's weight -- [{"name": "SQL", "weight": 1.0}].
    # Weight is 1, 0.5 or 0 (0 = shown but not scored). NULL = not set yet;
    # the list is then derived from the description (see skill_items_effective).
    skill_items: Mapped[list] = mapped_column(JSON, nullable=True)
    # Only for "skill" criteria: the mark (0-1) a RELATED skill earns, e.g.
    # Tableau for Power BI. NULL = the default 0.5.
    related_mark: Mapped[float] = mapped_column(Float, nullable=True)

    # Index into the source post's "criteria" list (within
    # job_profile.source_jd_upload.gemini_raw_response) that this
    # criterion was originally created from. Set at creation time from a
    # Gemini parse and never changed afterward (unlike display_order,
    # which HR can freely reorder) -- this is what lets the restore
    # endpoint tell "still present" apart from "was deleted" reliably.
    # Null for criteria HR added manually (no source to restore from).
    source_index: Mapped[int] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    job_profile: Mapped["JobProfile"] = relationship(back_populates="criteria")

    @property
    def skill_items_effective(self) -> Optional[list[dict]]:
        """The skill list screening marks against: HR's list when set,
        otherwise one split from the description. None for non-skill types."""
        if self.type != "skill":
            return None
        return normalize_skill_items(self.skill_items, self.description)

    @property
    def related_mark_effective(self) -> Optional[float]:
        """The related-skill mark screening uses; None for non-skill types."""
        if self.type != "skill":
            return None
        return normalize_related_mark(self.related_mark)


class AgeRelaxationRule(Base):
    __tablename__ = "age_relaxation_rules"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_profile_id: Mapped[str] = mapped_column(ForeignKey("job_profiles.id"))

    raw_category: Mapped[str] = mapped_column(String(500))       # exactly as returned by Gemini
    normalized_category: Mapped[str] = mapped_column(String(500))  # SC/ST/OBC/PwD_General/etc.
    relaxation_text: Mapped[str] = mapped_column(String(200))    # "5 years", "service period + 3 years"

    job_profile: Mapped["JobProfile"] = relationship(back_populates="age_relaxation_rules")
