"""
Candidate evaluation service.

Orchestrates the full screening of one candidate against one Job Profile's
criteria:
  - "age" type criteria are evaluated with pure rule-based logic (DOB +
    relaxation table), never sent to Gemini -- age is a calculable fact,
    not something an LLM should be asked to judge.
  - All other criteria types (education/experience/skill/other) are sent
    to Gemini in ONE batched call, with a citation attached to each result.
  - Once every criterion has a result, a final bucket is computed from
    the ESSENTIAL criteria only (desirable/preferred criteria are still
    evaluated and shown, but don't gate eligibility).

This logic was validated as standalone scripts (test_criterion_evaluation.py,
test_full_evaluation.py) against real candidate documents before being wired
in here.
"""

import hashlib
import json
import os
import re
from datetime import date, datetime
from typing import Optional

from app.models.job_profile import JobProfile, Criterion
from app.models.candidate import Candidate, CandidateDocument
from app.models.department_template import DepartmentTemplate
from app.models.criterion_evaluation import CriterionEvaluation
from app.services.gemini_service import (
    evaluate_criteria_batch_with_gemini,
    extract_cv_certifications_with_gemini,
    check_resume_roster_consistency_with_gemini,
    classify_government_experience_with_gemini,
    extract_resume_details_with_gemini,
    assess_competencies_with_gemini,
)
from app.services.criteria_utils import rescore_skill_marks, score_skill_matches, skill_score_summary
from app.services.pdf_extraction import (
    extract_marked_pdf_text_with_ocr, extract_text_from_docx, pdf_text_is_meaningful,
)
from app.services.age_relaxation import (
    evaluate_age_criterion, normalize_candidate_category, parse_age_limits_from_text,
)
from sqlalchemy import func


# Rule-based checks run BEFORE Gemini: a candidate who fails an essential
# age limit is rejected without a single token being spent on them. Set
# PREFILTER_BY_AGE=0 to evaluate everything regardless (e.g. to compare).
PREFILTER_BY_AGE = os.getenv("PREFILTER_BY_AGE", "1") != "0"

# Ingestion states that can be screened: every expected document was matched,
# a roster-only candidate is judged from the sheet row alone, or a
# resume-only candidate (ZIP of resumes, no roster) is judged from the resume.
SCREENABLE_STATUSES = ("documents_complete", "roster_only", "resume_only")


def criteria_fingerprint(profile: JobProfile) -> str:
    """
    Hash of everything a screening result depends on that can only be
    brought up to date by re-screening: each criterion's wording, type,
    essential flag and minimum match %, the skill names Gemini classifies,
    and the age limits / relaxation rules.

    Deliberately NOT included: competency weights, skill weights, the related mark, the
    experience tolerance, thresholds and suitability weights -- changes to
    those are re-applied to saved results straight away
    (reapply_screening_rules), so they never leave a result outdated.
    """
    payload = {
        "criteria": sorted(
            (
                {
                    "id": c.id,
                    "type": c.type,
                    "description": (c.description or "").strip(),
                    "essential": bool(c.is_essential),
                    "min_pct": c.required_match_percentage,
                    "skills": [i["name"] for i in c.skill_items_effective or []] if c.type == "skill" else None,
                }
                for c in profile.criteria
            ),
            key=lambda c: c["id"],
        ),
        "competencies": [
            {"key": c["key"], "name": c["name"], "description": c["description"]}
            for c in profile.competencies
        ],
        "age": [profile.base_age_min, profile.base_age_max],
        "relaxations": sorted(
            [r.normalized_category or "", r.relaxation_text or ""] for r in profile.age_relaxation_rules
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def results_outdated(candidate: Candidate, current_fingerprint: str) -> Optional[bool]:
    """True when the candidate's saved result was produced under criteria
    that have since changed; None when they have no result yet."""
    if candidate.computed_status is None:
        return None
    return candidate.criteria_fingerprint != current_fingerprint


# Stored for results screened before fingerprints existed whose criteria
# were edited after screening -- never equal to a real fingerprint.
_PRE_TRACKING_OUTDATED = "outdated-before-tracking"


def backfill_criteria_fingerprints(db) -> None:
    """
    One-time backfill for results screened before fingerprints existed: a
    result is taken as current when it is newer than the last criteria
    edit, otherwise as outdated. (Best effort -- a criterion deleted after
    screening can't be seen, and a weights-only edit reads as outdated.)
    """
    candidates = (
        db.query(Candidate)
        .filter(Candidate.computed_status.isnot(None), Candidate.criteria_fingerprint.is_(None))
        .all()
    )
    if not candidates:
        return
    evaluated_at = dict(
        db.query(CriterionEvaluation.candidate_id, func.max(CriterionEvaluation.evaluated_at))
        .filter(CriterionEvaluation.candidate_id.in_([c.id for c in candidates]))
        .group_by(CriterionEvaluation.candidate_id)
        .all()
    )
    profiles: dict[str, tuple[str, Optional[datetime]]] = {}
    for candidate in candidates:
        if candidate.job_profile_id not in profiles:
            profile = db.query(JobProfile).filter(JobProfile.id == candidate.job_profile_id).first()
            if profile is None:
                continue
            changed_at = max(
                (max(c.created_at or datetime.min, c.updated_at or datetime.min) for c in profile.criteria),
                default=None,
            )
            profiles[candidate.job_profile_id] = (criteria_fingerprint(profile), changed_at)
        fingerprint, changed_at = profiles[candidate.job_profile_id]
        screened_at = evaluated_at.get(candidate.id)
        current = changed_at is None or screened_at is None or screened_at >= changed_at
        candidate.criteria_fingerprint = fingerprint if current else _PRE_TRACKING_OUTDATED
    db.commit()


def build_document_context(documents: list[CandidateDocument]) -> str:
    """
    Builds one text blob covering every PDF document for a candidate, with
    clear markers around each page so Gemini can cite exactly where it
    found something. Non-PDF documents (photograph, signature images)
    carry no evaluable text and are skipped.

    Uses the text cached on CandidateDocument.extracted_text (populated at
    ingestion time). Scanned/image PDFs -- which have no text layer, so
    ingestion caches nothing useful for them -- are extracted here through
    the Gemini-vision OCR fallback and written back, so each scanned page
    is transcribed once, ever. The caller's commit persists the backfill.
    """
    context_parts = []

    for doc in documents:
        is_pdf = doc.file_path.lower().endswith(".pdf")

        if doc.file_path.lower().endswith(".docx"):
            # Word resumes (resume-only uploads): plain text, read once.
            if doc.extracted_text is None and os.path.exists(doc.file_path):
                try:
                    text = extract_text_from_docx(doc.file_path)
                    doc.extracted_text = f"--- DOCUMENT: {doc.original_filename} | PAGE: 1 ---\n{text}\n"
                except Exception:
                    doc.extracted_text = ""
            if doc.extracted_text:
                context_parts.append(doc.extracted_text)
            continue

        if not is_pdf:
            # Photos/signatures carry no evaluable text.
            if doc.extracted_text is None:
                doc.extracted_text = ""
            continue

        if doc.extracted_text is not None and pdf_text_is_meaningful(doc.extracted_text):
            context_parts.append(doc.extracted_text)
            continue

        if not os.path.exists(doc.file_path):
            continue

        try:
            # Full extraction with OCR fallback for scanned pages. Also
            # covers rows cached before OCR existed (marker-only text).
            doc.extracted_text = extract_marked_pdf_text_with_ocr(
                doc.file_path, doc.original_filename
            )
        except Exception:
            # A single unreadable/corrupt document shouldn't block
            # evaluation of the rest -- just skip it.
            continue

        if doc.extracted_text:
            context_parts.append(doc.extracted_text)

    return "\n".join(context_parts)


def build_declared_data_context(candidate: Candidate) -> str:
    """
    Formats the candidate's declared application data (their Excel roster
    row, captured at ingestion) for the evaluation prompt. Every criterion
    is checked in two stages -- declared-vs-JD, then documents-vs-declared
    -- so the model needs the declarations alongside the document proof.

    Document URL values are skipped: they're internal file references, not
    something the candidate declared. Resume-only candidates have no
    declared data at all -- the resume is their only evidence.
    """
    if candidate.ingestion_status == "resume_only":
        return ""
    data = candidate.raw_excel_data or {}
    lines = []
    for key, value in data.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text or text.lower() in ("nan", "n/a", "na", "none"):
            continue
        if text.lower().startswith("http"):
            continue
        lines.append(f"{key}: {text}")
    return "\n".join(lines)


def compute_final_status(evaluations: list[CriterionEvaluation], criteria_by_id: dict) -> str:
    """
    Final bucket logic:
        - any ESSENTIAL criterion result == "fail"          -> not_eligible
        - no essential fails, but any essential is           -> needs_review
          "needs_review"
        - all essential criteria pass                        -> eligible

    The consolidated SKILL criterion is non-essential by default (its match
    percentage is informational). It participates here only when HR has
    explicitly marked it essential -- in which case its pass/fail was
    decided by the minimum-match-percentage threshold during evaluation.
    """
    essential_results = [
        e.result for e in evaluations if criteria_by_id[e.criterion_id].is_essential
    ]

    if "fail" in essential_results:
        return "not_eligible"
    if "needs_review" in essential_results:
        return "needs_review"
    return "eligible"


_SKILL_GATE_PREFIX = re.compile(r"^Skills match \d+% (?:meets|is below) the required minimum of \d+%\. ")


def skill_gate(criterion: Criterion, pct: Optional[int], reasoning: Optional[str]) -> tuple[str, str]:
    """(result, reasoning) of the skill criterion. The skills score is
    informational by default; only when HR marked the criterion essential
    AND set a minimum match percentage does it become a real gate."""
    reasoning = _SKILL_GATE_PREFIX.sub("", reasoning or "")
    if not (criterion.is_essential and criterion.required_match_percentage is not None):
        return "pass", reasoning
    pct, threshold = pct or 0, criterion.required_match_percentage
    if pct >= threshold:
        return "pass", f"Skills match {pct}% meets the required minimum of {threshold}%. " + reasoning
    return "fail", f"Skills match {pct}% is below the required minimum of {threshold}%. " + reasoning


def rescore_skill_evaluation(e: CriterionEvaluation, criterion: Criterion) -> None:
    """Applies the post's current skill weights and related mark to a saved
    skill evaluation (its stored levels are reused; no Gemini call). Left
    alone when a skill was added after screening -- that needs a re-screen."""
    rescored = rescore_skill_marks(criterion.skill_items_effective, e.skill_marks, criterion.related_mark_effective)
    if rescored is None:
        return
    marks, pct = rescored
    body = _SKILL_GATE_PREFIX.sub("", e.reasoning or "")
    old_summary = skill_score_summary(e.skill_marks)
    if body.startswith(old_summary):
        body = body[len(old_summary):].lstrip()
    e.skill_marks, e.match_percentage = marks, pct
    e.result, e.reasoning = skill_gate(criterion, pct, skill_score_summary(marks) + " " + body)


def compute_section_scores(evaluations: list[CriterionEvaluation], criteria_by_id: dict) -> dict[str, Optional[float]]:
    """0-100 score per soft section -- skills, experience, desirable items
    (non-essential education / other criteria: pass 100, review 50, fail 0).
    None for a section the post doesn't have or that couldn't be scored."""
    def pcts(criterion_type):
        return [
            e.match_percentage for e in evaluations
            if criteria_by_id[e.criterion_id].type == criterion_type and e.match_percentage is not None
        ]

    points = {"pass": 100, "needs_review": 50, "fail": 0}
    desirable = [
        points.get(e.result, 0) for e in evaluations
        if not criteria_by_id[e.criterion_id].is_essential
        and criteria_by_id[e.criterion_id].type in ("education", "other")
    ]
    return {
        name: (sum(values) / len(values) if values else None)
        for name, values in (
            ("skills", pcts("skill")),
            ("experience", pcts("experience")),
            ("desirable", desirable),
        )
    }


def compute_suitability(
    evaluations: list[CriterionEvaluation], criteria_by_id: dict, profile: JobProfile,
    competency_scores: Optional[list[dict]] = None,
) -> Optional[int]:
    """
    0-100 weighted score over the post's SOFT sections, used to rank
    candidates: skills match, desirable items and each competency
    (projects, leadership, communication, ... scored 0-5 -> 0-100). Weights
    come from the profile and are renormalised over the sections that could
    actually be scored for this candidate. None when no section can be scored.

    Experience is deliberately left out: its match % is capped at 100, so
    every candidate who meets the must-have experience scores the same and
    it would never separate them. Shortfalls are handled by the experience
    tolerance (near-miss) rule instead.
    """
    sections = compute_section_scores(evaluations, criteria_by_id)
    weights = {
        "skills": profile.weight_skills,
        "desirable": profile.weight_desirable,
    }
    scored = [(sections[k], w) for k, w in weights.items() if sections[k] is not None and w and w > 0]
    by_key = {s.get("key"): s for s in competency_scores or [] if isinstance(s, dict)}
    for comp in profile.competencies:
        found = by_key.get(comp["key"])
        if found is not None and found.get("score") is not None and comp["weight"] > 0:
            scored.append((found["score"] * 20, comp["weight"]))
    if not scored:
        return None
    return round(sum(score * w for score, w in scored) / sum(w for _, w in scored))


def close_miss_note(sections: dict[str, Optional[float]], profile: JobProfile) -> Optional[str]:
    """For a NOT ELIGIBLE candidate: the 'close miss' note when they score at
    least the post's minimum in any section HR switched on, else None."""
    minimums = {
        "skills": profile.close_miss_skills_min,
        "experience": profile.close_miss_experience_min,
        "desirable": profile.close_miss_desirable_min,
    }
    hits = [
        f"{name} {round(sections[name])}% (minimum {minimum}%)"
        for name, minimum in minimums.items()
        if minimum is not None and sections[name] is not None and sections[name] >= minimum
    ]
    return "Not eligible, but scores well: " + "; ".join(hits) if hits else None


def experience_near_miss(
    gemini_result: dict, skills_pct: Optional[int], profile: JobProfile, candidate: Candidate
) -> tuple[Optional[str], Optional[str]]:
    """
    (review_tag, note) when a FAILED essential experience criterion is only
    a near-miss -- short by no more than the post's tolerance -- and the
    candidate deserves a human look instead of a rejection:
      strong_exception -> their skills match meets the exception threshold
      awaiting_resume  -> the skills can't be judged until the resume is
                          fetched (roster-only candidates)
    (None, None) means a genuine fail.
    """
    documented = gemini_result.get("documented_years")
    required = gemini_result.get("required_years")
    if documented is None or required is None:
        return None, None
    shortfall = round(required - documented, 1)
    tolerance = profile.experience_tolerance_years if profile.experience_tolerance_years is not None else 2.0
    if shortfall <= 0 or shortfall > tolerance:
        return None, None

    short = f"experience {shortfall:g} yr short of {required:g} required ({documented:g} counted)"
    threshold = profile.exception_skills_threshold if profile.exception_skills_threshold is not None else 80
    if skills_pct is not None and skills_pct >= threshold:
        return "strong_exception", f"Strong candidate, with exception: {short}; skills match {skills_pct}%"

    has_resume = any(d.document_type == "resume_cv" for d in candidate.documents)
    if candidate.resume_fetch_status in ("pending", "fetching") and not has_resume:
        return "awaiting_resume", f"Near miss: {short}; skills can only be judged once the resume is fetched"
    return None, None


def extract_cv_certifications(cv_context: str) -> tuple[Optional[list[dict]], Optional[bool]]:
    """
    Returns (certifications, has_cyber_security_certification) for the
    candidate's CV text. Both are None when there's no readable CV to
    extract from, or when Gemini couldn't produce a valid list -- None
    means "unknown / not extracted", which the Results and export screens
    show differently from "the CV lists no certificates" ([] / False).
    """
    if not cv_context or not cv_context.strip():
        return None, None
    try:
        certifications = extract_cv_certifications_with_gemini(cv_context)
    except Exception:
        return None, None
    return certifications, None


def check_resume_consistency(candidate: Candidate, profile: JobProfile, cv_context: str) -> Optional[dict]:
    """
    Resume-vs-roster consistency on experience and the must-have (essential)
    criteria. None when it can't be checked (no readable CV, no roster data,
    or Gemini failed). Informational only -- a failure here is swallowed,
    like the certification extraction, and never blocks screening.
    """
    declared = build_declared_data_context(candidate)
    if not cv_context.strip() or not declared:
        return None
    must_haves = [
        f"[{c.type}] {c.description}"
        for c in profile.criteria
        if c.is_essential and c.type != "age"
    ]
    try:
        return check_resume_roster_consistency_with_gemini(declared, cv_context, must_haves)
    except Exception:
        return None


def fill_details_from_resume(candidate: Candidate) -> None:
    """Resume-only candidates: name, email, phone, DOB, gender and category
    read from the resume (one small Gemini call). Fields the resume doesn't
    state keep their current value (the name guessed from the file name).
    A failure is swallowed -- screening still runs, the age check simply
    goes to review without a DOB."""
    cv_context = build_document_context(
        [d for d in candidate.documents if d.document_type == "resume_cv"]
    )
    if not cv_context.strip():
        return
    try:
        details = extract_resume_details_with_gemini(cv_context)
    except Exception:
        return
    for field in ("name", "email", "phone", "dob", "gender"):
        if details.get(field):
            setattr(candidate, field, details[field])
    if details.get("category"):
        candidate.raw_category = details["category"]
        candidate.normalized_category = normalize_candidate_category(details["category"])


def _post_summary(profile: JobProfile) -> str:
    """The post's title plus its experience and skill requirements -- what
    'relevant to the post' is judged against."""
    lines = [f"Post: {profile.title}"]
    lines += [
        f"- [{c.type}] {c.description}"
        for c in profile.criteria
        if c.type in ("experience", "skill")
    ]
    return "\n".join(lines)


def check_competencies(candidate: Candidate, profile: JobProfile, document_context: str, cv_context: str) -> Optional[list[dict]]:
    """The post's competencies scored 0-5 from the candidate's documents
    (resume first). None when there is nothing to read, the post has no
    competencies, or Gemini failed -- informational, never blocks screening."""
    competencies = profile.competencies
    documents = "\n\n".join(part for part in (cv_context, document_context) if part and part.strip())
    declared = build_declared_data_context(candidate)
    if declared:
        documents = f"APPLICATION DATA (declared by the candidate):\n{declared}\n\n{documents}"
    if not competencies or not documents.strip():
        return None
    try:
        return assess_competencies_with_gemini(documents, competencies, _post_summary(profile))
    except Exception:
        return None


def check_government_experience(candidate: Candidate, profile: JobProfile, cv_context: str) -> tuple[Optional[dict], Optional[bool]]:
    """(gov_experience, gov_relevant_experience) for the Government Relevant
    Experience tag. (None, None) when it can't be checked (no work history
    to read, or Gemini failed) -- informational, never blocks screening."""
    declared = build_declared_data_context(candidate)
    if not declared and not cv_context.strip():
        return None, None
    try:
        result = classify_government_experience_with_gemini(declared, cv_context, _post_summary(profile))
    except Exception:
        return None, None
    return {"jobs": result["jobs"]}, result["has_relevant"]


def mismatch_flag(status: str, candidate: Candidate) -> tuple[str, Optional[str], Optional[str]]:
    """Sheet vs resume mismatch: an eligible or needs-review candidate whose
    resume contradicts the sheet is needs review, tagged data_mismatch (the
    resume-vs-roster consistency check is the only place mismatches are
    detected). The score is never lowered and a not-eligible candidate
    stays not eligible. Returns (status, tag, note); tag/note None when
    nothing changes."""
    consistency = candidate.resume_consistency or {}
    if status not in ("eligible", "needs_review") or consistency.get("overall") != "inconsistent":
        return status, None, None
    items = [c.get("item") or "item" for c in consistency.get("checks", []) if c.get("verdict") == "inconsistent"]
    return "needs_review", "data_mismatch", "Sheet and resume disagree on: " + "; ".join(items)


def _age_evaluation(
    criterion: Criterion, candidate: Candidate, profile: JobProfile, relaxation_rules: list[dict]
) -> CriterionEvaluation:
    """Rule-based, no Gemini -- age is a calculable fact. The criterion's
    CURRENT description is the source of truth for the limits, so HR edits
    take effect on the next screen; the profile's JD-parse-time numbers are
    only the fallback when the text has no parseable limits."""
    desc_min, desc_max = parse_age_limits_from_text(criterion.description)
    limits_from_description = desc_min is not None or desc_max is not None
    result = evaluate_age_criterion(
        dob_str=candidate.dob,
        normalized_category=candidate.normalized_category,
        base_age_min=desc_min if limits_from_description else profile.base_age_min,
        base_age_max=desc_max if limits_from_description else profile.base_age_max,
        age_relaxation_rules=relaxation_rules,
        as_of=date.today(),
    )
    return CriterionEvaluation(
        candidate_id=candidate.id,
        criterion_id=criterion.id,
        result=result["result"],
        citation_document=None,
        citation_page=None,
        reasoning=result["reasoning"],
    )


def _store_outcome(
    candidate: Candidate, status: str, review_tag: Optional[str], review_note: Optional[str],
    suitability: Optional[int],
) -> None:
    """A fresh evaluation is the new authoritative assessment -- any prior
    HR override is cleared, since it was based on an older (possibly
    now-outdated) evaluation. HR can always re-override after reviewing
    the new result."""
    candidate.computed_status = status
    candidate.status = status
    candidate.review_tag = review_tag
    candidate.review_note = review_note
    candidate.suitability_score = suitability
    candidate.status_overridden = False
    candidate.override_reason = None
    candidate.overridden_by = None
    candidate.overridden_at = None


def evaluate_candidate(db, candidate: Candidate, profile: JobProfile) -> list[CriterionEvaluation]:
    """
    Evaluates every criterion in `profile` against `candidate`, saves a
    CriterionEvaluation row for each, updates candidate.status, and
    returns the list of created evaluation rows.

    Assumes the caller has already checked the candidate is screenable
    (ingestion_status in SCREENABLE_STATUSES) -- this function does not skip
    anything itself.
    """
    # Recorded up front: the result produced below reflects exactly this
    # criteria state (rolled back with everything else if evaluation fails).
    candidate.criteria_fingerprint = criteria_fingerprint(profile)

    # A fresh evaluation REPLACES the candidate's previous results -- old
    # rows must go first, or re-screening appends a duplicate breakdown for
    # every criterion. (Runs in the caller's transaction: if evaluation
    # fails mid-way, the rollback restores the previous results.)
    db.query(CriterionEvaluation).filter(
        CriterionEvaluation.candidate_id == candidate.id
    ).delete(synchronize_session=False)

    # The CV is the candidate's own writing -- a claims source, never
    # proof. It's split OUT of the document evidence and handed to the
    # prompt separately, where it fills gaps in the declared application
    # data (facts the Excel row doesn't mention). A claim satisfied only
    # by the CV with no proving document ends in "needs_review".
    resume_only = candidate.ingestion_status == "resume_only"
    if resume_only:
        # No roster row: name, contact details and the DOB the age check
        # needs come from the resume itself.
        fill_details_from_resume(candidate)

    age_relaxation_rules_for_lookup = [
        {"normalized_category": r.normalized_category, "relaxation_text": r.relaxation_text}
        for r in profile.age_relaxation_rules
    ]
    age_evaluations = {
        c.id: _age_evaluation(c, candidate, profile, age_relaxation_rules_for_lookup)
        for c in profile.criteria if c.type == "age"
    }
    if PREFILTER_BY_AGE and any(
        c.is_essential and age_evaluations[c.id].result == "fail"
        for c in profile.criteria if c.type == "age"
    ):
        # Rule-based rejection: no documents are read and Gemini is never called.
        for evaluation in age_evaluations.values():
            db.add(evaluation)
        candidate.cv_certifications, candidate.has_cyber_security_certification = None, None
        candidate.resume_consistency = None
        candidate.gov_experience, candidate.gov_relevant_experience = None, None
        candidate.competency_scores = None
        _store_outcome(candidate, "not_eligible", None, None, None)
        return list(age_evaluations.values())

    cv_documents = [d for d in candidate.documents if d.document_type == "resume_cv"]
    proof_documents = [d for d in candidate.documents if d.document_type != "resume_cv"]
    document_context = build_document_context(proof_documents)
    cv_context = build_document_context(cv_documents)

    created_evaluations: list[CriterionEvaluation] = []
    criteria_by_id = {}

    # All non-age criteria are evaluated in ONE Gemini call (the document
    # context -- by far the bulk of the prompt -- is sent once, not once
    # per criterion). Age criteria stay rule-based, never sent to Gemini.
    non_age_criteria = [c for c in profile.criteria if c.type != "age"]
    evidence_mode = "documents_primary"
    if profile.department_template_id:
        template = db.query(DepartmentTemplate).filter(
            DepartmentTemplate.id == profile.department_template_id
        ).first()
        if template:
            evidence_mode = template.evidence_mode
    if candidate.resume_fetch_status is not None:
        # Roster-only candidate: the sheet row is the evidence and the
        # resume (when fetched) corroborates it; no proof documents exist.
        evidence_mode = "declared_primary"
    if resume_only:
        # ZIP of resumes, no roster: the resume is the whole truth.
        evidence_mode = "resume_only"
    batch_results = evaluate_criteria_batch_with_gemini(
        document_context,
        [
            {
                "type": c.type,
                "description": c.description,
                "skill_items": [i["name"] for i in c.skill_items_effective or []],
            }
            for c in non_age_criteria
        ],
        declared_data=build_declared_data_context(candidate),
        cv_context=cv_context,
        evidence_mode=evidence_mode,
    )
    gemini_result_by_criterion_id = {
        criterion.id: result for criterion, result in zip(non_age_criteria, batch_results)
    }
    for criterion, result in zip(non_age_criteria, batch_results):
        # Gemini classified each skill (same / related / none); the fixed
        # marks and HR's weights turn that into the score. The per-criterion
        # fallback path returns no classification, so no score either.
        if criterion.type == "skill" and result.get("skill_matches"):
            marks, pct = score_skill_matches(
                criterion.skill_items_effective, result["skill_matches"], criterion.related_mark_effective
            )
            result["skill_marks"], result["match_percentage"] = marks, pct
            result["reasoning"] = skill_score_summary(marks) + " " + (result.get("reasoning") or "")

    skills_pct = next(
        (
            result.get("match_percentage")
            for criterion, result in zip(non_age_criteria, batch_results)
            if criterion.type == "skill"
        ),
        None,
    )
    review_tags: list[tuple[str, str]] = []

    for criterion in profile.criteria:
        criteria_by_id[criterion.id] = criterion

        if criterion.type == "age":
            evaluation = age_evaluations[criterion.id]
        else:
            gemini_result = gemini_result_by_criterion_id[criterion.id]
            result_value = gemini_result["result"]
            reasoning = gemini_result["reasoning"]

            if criterion.type == "skill":
                result_value, reasoning = skill_gate(criterion, gemini_result.get("match_percentage"), reasoning)

            elif criterion.type == "experience" and criterion.is_essential and result_value == "fail":
                # Near-miss on a must-have experience requirement: not a
                # rejection when the shortfall is within the post's
                # tolerance and the skills are strong (or still unknown).
                tag, note = experience_near_miss(gemini_result, skills_pct, profile, candidate)
                if tag:
                    result_value = "needs_review"
                    reasoning = f"{note}. " + (reasoning or "")
                    review_tags.append((tag, note))

            evaluation = CriterionEvaluation(
                candidate_id=candidate.id,
                criterion_id=criterion.id,
                result=result_value,
                match_percentage=gemini_result.get("match_percentage"),
                skill_marks=gemini_result.get("skill_marks"),
                citation_document=gemini_result["citation"]["document"],
                citation_page=gemini_result["citation"]["page"],
                reasoning=reasoning,
            )

        db.add(evaluation)
        created_evaluations.append(evaluation)

    final_status = compute_final_status(created_evaluations, criteria_by_id)

    # Certificates listed in the CV (and whether each is cyber-security
    # related) are extracted alongside the criteria check, in a separate
    # small Gemini call that only sees the CV text. This is informational
    # -- it never changes the eligibility bucket -- so a failure here is
    # swallowed rather than failing the whole screening: the columns simply
    # stay empty ("not extracted") for this candidate until the next run.
    candidate.cv_certifications, candidate.has_cyber_security_certification = (
        extract_cv_certifications(cv_context)
    )
    candidate.resume_consistency = check_resume_consistency(candidate, profile, cv_context)

    # Strong exceptions outrank "awaiting resume" when both apply.
    review_tags.sort(key=lambda t: t[0] != "strong_exception")
    tag, note = review_tags[0] if review_tags and final_status == "needs_review" else (None, None)
    final_status, mismatch_tag, mismatch_note = mismatch_flag(final_status, candidate)
    if mismatch_tag:
        tag, note = mismatch_tag, mismatch_note

    # Government Relevant Experience: only eligible / needs-review
    # candidates can carry the tag, so not-eligible ones cost no call.
    if final_status == "not_eligible":
        candidate.gov_experience, candidate.gov_relevant_experience = None, None
    else:
        candidate.gov_experience, candidate.gov_relevant_experience = (
            check_government_experience(candidate, profile, cv_context)
        )

    # Competencies (projects, leadership, communication, ...) feed the
    # suitability score that ranks candidates, so like the government
    # check they are only assessed for eligible / needs-review candidates.
    candidate.competency_scores = (
        None if final_status == "not_eligible"
        else check_competencies(candidate, profile, document_context, cv_context)
    )

    if final_status == "not_eligible":
        close_miss = close_miss_note(compute_section_scores(created_evaluations, criteria_by_id), profile)
        if close_miss:
            tag, note = "close_miss", close_miss
    _store_outcome(
        candidate, final_status, tag, note,
        compute_suitability(created_evaluations, criteria_by_id, profile, candidate.competency_scores),
    )

    return created_evaluations


# ---------------------------------------------------------------------------
# Re-applying the post's settings to results that are already saved.
#
# The near-miss rule (tolerance + skills threshold) and the suitability
# weights only need numbers that are stored with every evaluation: the
# experience match % is "years counted / years required", and the skills
# match % is stored too. So when HR changes a setting the existing results
# are re-derived from those numbers -- no Gemini call, no re-screening.
# ---------------------------------------------------------------------------

_NEAR_MISS_PREFIX = re.compile(
    r"^(?:Strong candidate, with exception|Near miss): .*?; skills "
    r"(?:match \d+%|can only be judged once the resume is fetched)\.\s*",
    re.DOTALL,
)


def _required_years(description: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", description or "", re.IGNORECASE)
    return float(match.group(1)) if match else None


def reapply_screening_rules(db, profile: JobProfile) -> int:
    """Re-derives every screened candidate's near-miss outcome, status, tag
    and suitability score from the saved evaluations and the profile's
    current settings. HR overrides are left alone (only the computed values
    move). Returns how many candidates changed. The caller commits."""
    criteria_by_id = {c.id: c for c in profile.criteria}
    candidates = (
        db.query(Candidate)
        .filter(Candidate.job_profile_id == profile.id, Candidate.computed_status.isnot(None))
        .all()
    )
    changed = 0
    for candidate in candidates:
        # Two overlapping screenings of the same candidate can each leave a
        # row per criterion; the newest is the authoritative one.
        newest: dict[str, CriterionEvaluation] = {}
        for e in sorted(
            db.query(CriterionEvaluation).filter(CriterionEvaluation.candidate_id == candidate.id).all(),
            key=lambda row: row.evaluated_at or datetime.min,
        ):
            if e.criterion_id in newest:
                db.delete(newest[e.criterion_id])
            if e.criterion_id in criteria_by_id:
                newest[e.criterion_id] = e
        evaluations = list(newest.values())
        if not evaluations:
            continue
        for e in evaluations:
            if criteria_by_id[e.criterion_id].type == "skill" and e.skill_marks:
                rescore_skill_evaluation(e, criteria_by_id[e.criterion_id])
        skills_pct = next(
            (e.match_percentage for e in evaluations if criteria_by_id[e.criterion_id].type == "skill"), None
        )
        review_tags: list[tuple[str, str]] = []
        for e in evaluations:
            criterion = criteria_by_id[e.criterion_id]
            if criterion.type != "experience" or not criterion.is_essential:
                continue
            was_near_miss = e.result == "needs_review" and bool(_NEAR_MISS_PREFIX.match(e.reasoning or ""))
            if e.result != "fail" and not was_near_miss:
                continue
            required = _required_years(criterion.description)
            if required is None or e.match_percentage is None:
                continue
            documented = round(required * e.match_percentage / 100, 1)
            tag, note = experience_near_miss(
                {"documented_years": documented, "required_years": required}, skills_pct, profile, candidate
            )
            original = _NEAR_MISS_PREFIX.sub("", e.reasoning or "")
            if tag:
                e.result, e.reasoning = "needs_review", f"{note}. {original}"
                review_tags.append((tag, note))
            else:
                e.result, e.reasoning = "fail", original

        status = compute_final_status(evaluations, criteria_by_id)
        review_tags.sort(key=lambda t: t[0] != "strong_exception")
        tag, note = review_tags[0] if review_tags and status == "needs_review" else (None, None)
        if tag is None and candidate.review_tag == "resume_unavailable" and status in ("eligible", "needs_review"):
            status, tag, note = "needs_review", candidate.review_tag, candidate.review_note
        status, mismatch_tag, mismatch_note = mismatch_flag(status, candidate)
        if mismatch_tag:
            tag, note = mismatch_tag, mismatch_note
        suitability = compute_suitability(evaluations, criteria_by_id, profile, candidate.competency_scores)

        before = (candidate.computed_status, candidate.review_tag, candidate.suitability_score)
        candidate.computed_status = status
        if not candidate.status_overridden:
            candidate.status = status
        candidate.review_tag, candidate.review_note = tag, note
        candidate.suitability_score = suitability
        if before != (candidate.computed_status, candidate.review_tag, candidate.suitability_score):
            changed += 1
    return changed
