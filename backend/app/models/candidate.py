"""
Candidate + CandidateDocument models.

A Candidate belongs to one JobProfile (they were uploaded to be screened
against that specific post). Their documents are matched from the master
ZIP using the candidate master Excel as the source of truth for which
file is which document type (see services/candidate_ingestion.py).

Note: ingestion_status and status are kept as two separate fields on
purpose -- ingestion_status tracks whether we could even find/match this
candidate's documents (a data problem), while status tracks the actual
screening outcome (a decision about the candidate). This separation
matters because a candidate with missing documents should be visibly
"skipped", not silently counted as a failed evaluation.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, JSON, Boolean, Text, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    job_profile_id: Mapped[str] = mapped_column(ForeignKey("job_profiles.id"))

    # The Excel "Id." column, e.g. "IHM/JA/1900/10001" -- this is how we
    # match a candidate's Excel row to their folder in the documents ZIP.
    external_id: Mapped[str] = mapped_column(String(100), index=True)

    name: Mapped[str] = mapped_column(String(300), nullable=True)
    email: Mapped[str] = mapped_column(String(300), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)
    # Stored as string rather than a Date column -- source data formats can
    # be inconsistent, and we don't want ingestion to fail on a bad date.
    # Proper date parsing happens later, at screening time, when needed.
    dob: Mapped[str] = mapped_column(String(20), nullable=True)
    gender: Mapped[str] = mapped_column(String(20), nullable=True)

    raw_category: Mapped[str] = mapped_column(String(100), nullable=True)
    normalized_category: Mapped[str] = mapped_column(String(50), nullable=True)

    # Full Excel row, kept as-is for future reference (education history,
    # work experience, references, etc. -- fields we don't have dedicated
    # columns for yet).
    raw_excel_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Tracks what happened during document matching, so downstream screening
    # can skip evaluation (instead of wasting an LLM call) for candidates
    # whose documents are missing/incomplete.
    #   roster_only           -> sheet row only; documents/resume come later
    #   resume_only           -> ZIP of resumes, no roster: the resume is the
    #                            whole truth (details are read from it)
    #   documents_complete    -> every expected document was found
    #   documents_incomplete  -> some documents matched, some missing
    #   no_documents_found    -> ZIP extracted but nothing matched at all
    #   corrupt_zip           -> nested ZIP for this candidate couldn't be
    #                            read (legacy nested-ZIP uploads only)
    #   excel_row_not_found   -> a candidate ZIP existed but no matching Excel row
    ingestion_status: Mapped[str] = mapped_column(String(30), default="pending")

    # Screening outcome as computed by the automated evaluation (age rule +
    # Gemini). This is preserved even if HR later overrides the status, so
    # the original AI/rule-based assessment is never lost.
    computed_status: Mapped[str] = mapped_column(String(30), nullable=True)

    # The EFFECTIVE status -- what everyone (Results, Dashboard, etc.) sees.
    # Starts equal to computed_status once evaluated, but HR can override it
    # via the Manual Review screen (see status_overridden fields below).
    status: Mapped[str] = mapped_column(String(30), default="not_evaluated")

    # HR override tracking -- lets Manual Review show "AI said X, HR
    # changed it to Y, here's why" instead of silently losing that history.
    status_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str] = mapped_column(String(1000), nullable=True)
    overridden_by: Mapped[str] = mapped_column(ForeignKey("hr_users.id"), nullable=True)
    overridden_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # The batch ScreeningRun this candidate was last evaluated in -- lets
    # Results filter to "only candidates from screening X" (each run is one
    # criteria state at one point in time). Deliberately NOT a ForeignKey:
    # runs are deleted freely (delete-all-candidates, profile delete) and a
    # stale id here should just filter to nothing, not block the delete.
    last_screening_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=True, index=True
    )
    # Fingerprint of the criteria this candidate's result was produced
    # under (see candidate_evaluation.criteria_fingerprint). When it no
    # longer matches the profile's current one, the result is outdated and
    # needs a re-screen. NULL = never screened.
    criteria_fingerprint: Mapped[str] = mapped_column(String(64), nullable=True)

    # Certifications the candidate lists in their CV/resume, extracted by
    # Gemini during screening (see services/candidate_evaluation.py). A
    # list of {"name", "issuer", "year", "is_cyber_security", "reason"}
    # dicts. [] means the CV was read and lists no certifications; NULL
    # means nothing has been extracted (not screened yet, or no readable
    # CV was uploaded). Cleared on re-upload, like the screening results.
    cv_certifications: Mapped[list] = mapped_column(JSON, nullable=True)

    # True when at least one CV certification is cyber-security related
    # (information/network/cloud security, ethical hacking, forensics,
    # security audit/GRC ...). NULL whenever cv_certifications is NULL, so
    # "not extracted" is never mistaken for "no".
    has_cyber_security_certification: Mapped[bool] = mapped_column(Boolean, nullable=True)

    # Resume-vs-roster consistency check on the experience and must-have
    # (essential) items, produced during screening. {"overall":
    # "consistent"|"inconsistent"|"unverified", "checks": [{"item", "roster",
    # "resume", "verdict", "note"}]}. Informational -- never changes the
    # eligibility bucket. NULL = not checked (no CV, or not screened yet).
    resume_consistency: Mapped[dict] = mapped_column(JSON, nullable=True)

    # Roster-only uploads (no documents ZIP): the resume is fetched from the
    # link in the department's sheet AFTER the first, sheet-only screening.
    #   NULL      -> not a roster upload (documents came in a ZIP)
    #   no_link   -> the sheet row has no resume link
    #   pending   -> link known, not fetched yet
    #   fetching  -> download + re-screen in progress
    #   fetched   -> resume stored and the candidate re-screened with it
    #   failed    -> the link could not be downloaded (see resume_fetch_error)
    # Row position in the uploaded roster sheet (0-based). created_at can't
    # give the sheet order: a whole roster is inserted in one batch, so its
    # timestamps are all but identical.
    roster_position: Mapped[int] = mapped_column(Integer, nullable=True)
    resume_link: Mapped[str] = mapped_column(Text, nullable=True)
    resume_fetch_status: Mapped[str] = mapped_column(String(20), nullable=True)
    resume_fetch_error: Mapped[str] = mapped_column(String(500), nullable=True)

    # Why a "needs_review" candidate is in that bucket, when it is more
    # specific than "something was uncertain":
    #   strong_exception   -> misses an essential experience criterion by no
    #                         more than the post's tolerance, but skills are
    #                         exceptionally strong
    #   awaiting_resume    -> a near-miss on experience whose skills can only
    #                         be judged once the resume is fetched
    #   resume_unavailable -> shortlisted, but the resume couldn't be fetched
    # NULL for every other candidate. review_note is the human-readable detail.
    review_tag: Mapped[str] = mapped_column(String(30), nullable=True)
    review_note: Mapped[str] = mapped_column(String(500), nullable=True)

    # 0-100 weighted score over the post's soft sections (skills,
    # experience, desirable items); the Results ranking sorts by it.
    suitability_score: Mapped[int] = mapped_column(Integer, nullable=True)

    # The post's competencies scored from the resume, 0-5 each with the
    # quoted evidence: [{"key", "name", "score", "evidence", "document",
    # "page"}]. NULL = not assessed (not screened, age-rejected, not
    # eligible, or the Gemini call failed).
    competency_scores: Mapped[list] = mapped_column(JSON, nullable=True)

    # Government Relevant Experience. Only checked for candidates who are
    # eligible or need review (never for not-eligible ones).
    # gov_experience = {"jobs": [{"organisation", "designation", "period",
    # "is_government", "role_relevant", "reason"}], "summary"}; a job counts
    # only when it is government/GovTech AND relevant to the post.
    # gov_relevant_experience: True / False, NULL = not checked.
    gov_experience: Mapped[dict] = mapped_column(JSON, nullable=True)
    gov_relevant_experience: Mapped[bool] = mapped_column(Boolean, nullable=True)

    job_profile = relationship("JobProfile")

    @property
    def gov_tag(self) -> bool:
        """The tag shown and ranked on: never on a not-eligible candidate,
        even when HR overrides the status after the check ran."""
        return bool(self.gov_relevant_experience) and self.status in ("eligible", "needs_review")
    documents: Mapped[list["CandidateDocument"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"))

    # photograph / signature / 10th_marksheet / graduation_certificate /
    # salary_slip / resume_cv / pwbd_certificate / category_certificate /
    # experience_proof_1..8 / manual_document_N (single-candidate entry).
    # "resume_cv" is candidate-authored: evaluation feeds it to Gemini as
    # the candidate's own CLAIMS (a fallback when the Excel row is silent
    # on something), never as document proof.
    document_type: Mapped[str] = mapped_column(String(50))

    file_path: Mapped[str] = mapped_column(String(1000))
    original_filename: Mapped[str] = mapped_column(String(500))

    # Page-marked text extracted from the document (the exact blob sent to
    # Gemini during screening), cached at ingestion time so screening never
    # re-parses PDFs. "" for non-PDF/unreadable documents; NULL means "not
    # extracted yet" (rows from before this column existed -- backfilled
    # lazily on first screening).
    extracted_text: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    candidate: Mapped["Candidate"] = relationship(back_populates="documents")
