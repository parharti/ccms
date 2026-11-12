"""
Results endpoint -- shows candidates filtered by their final screening
status (Eligible / Not Eligible / Needs Review / Not Evaluated) and/or by
one specific screening run, plus an Excel export. Candidates are always
listed in upload order (the order of the roster Excel), NOT re-sorted by
status -- HR compares against the original sheet row by row.
"""

import io
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.job_profile import JobProfile
from app.models.candidate import Candidate
from app.models.job_profile import Criterion
from app.models.criterion_evaluation import CriterionEvaluation
from app.schemas.results import ResultsResponse, ResultsSummary
from app.services.auth_service import get_current_hr_user

router = APIRouter(
    prefix="/jd/profiles/{profile_id}/results",
    tags=["results"],
    dependencies=[Depends(get_current_hr_user)],
)

def _get_profile_or_404(profile_id: str, db: Session) -> JobProfile:
    profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Job Profile '{profile_id}' not found")
    return profile


_STATUS_RANK = {"eligible": 0, "needs_review": 1, "not_eligible": 2, "not_evaluated": 3}


def _attach_skill_match(db: Session, candidates: list[Candidate]) -> None:
    """Sets candidate.skill_match_percentage (a plain attribute, not a
    column) from each candidate's skill-criterion evaluation."""
    ids = [c.id for c in candidates]
    pct_by_candidate: dict[str, int] = {}
    if ids:
        rows = (
            db.query(CriterionEvaluation.candidate_id, CriterionEvaluation.match_percentage)
            .join(Criterion, Criterion.id == CriterionEvaluation.criterion_id)
            .filter(
                CriterionEvaluation.candidate_id.in_(ids),
                Criterion.type == "skill",
                CriterionEvaluation.match_percentage.isnot(None),
            )
            .all()
        )
        for candidate_id, pct in rows:
            pct_by_candidate[candidate_id] = pct
    for c in candidates:
        c.skill_match_percentage = pct_by_candidate.get(c.id)


def _wants_ranking(sort: Optional[str], profile: JobProfile) -> bool:
    """?sort=skill_match / ?sort=roster force a choice; otherwise the post's
    own "rank by suitability" setting decides."""
    if sort == "skill_match":
        return True
    if sort == "roster":
        return False
    return profile.rank_by_suitability is not False


def _rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Best first: eligible, then needs-review, then not-eligible. Within a
    group, candidates with the Government Relevant Experience tag come first
    (only eligible / needs-review ones can have it), then strong candidates
    with an exception, then higher suitability score, then higher skills
    match (unscored last). Stable, so ties keep roster order."""
    return sorted(
        candidates,
        key=lambda c: (
            _STATUS_RANK.get(c.status, 9),
            0 if c.gov_tag else 1,
            0 if c.review_tag in ("strong_exception", "close_miss") else 1,
            -(c.suitability_score if c.suitability_score is not None else -1),
            -(c.skill_match_percentage if c.skill_match_percentage is not None else -1),
        ),
    )


def _build_summary(all_candidates: list[Candidate]) -> ResultsSummary:
    return ResultsSummary(
        total=len(all_candidates),
        eligible=sum(1 for c in all_candidates if c.status == "eligible"),
        not_eligible=sum(1 for c in all_candidates if c.status == "not_eligible"),
        needs_review=sum(1 for c in all_candidates if c.status == "needs_review"),
        not_evaluated=sum(1 for c in all_candidates if c.status == "not_evaluated"),
    )


@router.get("", response_model=ResultsResponse)
def get_results(
    profile_id: str,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    sort: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Pass ?sort=skill_match to rank best-first (status bucket, then skills
    match %) instead of roster order.

    Returns a summary of candidate counts by status, plus the candidate
    list in upload (roster Excel) order. Pass ?status=eligible (or
    not_eligible / needs_review / not_evaluated) to filter to one bucket,
    and/or ?run_id=<screening run id> to see only the candidates screened
    in that particular run. The summary counts follow the run filter (but
    not the status filter), so the tiles describe the selected screening.
    """
    profile = _get_profile_or_404(profile_id, db)

    all_candidates = (
        db.query(Candidate)
        .filter(Candidate.job_profile_id == profile_id)
        .order_by(Candidate.roster_position, Candidate.created_at)
        .all()
    )
    if run_id is not None:
        all_candidates = [c for c in all_candidates if c.last_screening_run_id == run_id]
    summary = _build_summary(all_candidates)

    filtered = all_candidates if status is None else [c for c in all_candidates if c.status == status]
    _attach_skill_match(db, filtered)
    if _wants_ranking(sort, profile):
        filtered = _rank_candidates(filtered)

    return ResultsResponse(summary=summary, candidates=filtered)


# ---------------------------------------------------------------------------
# Excel export -- mirrors IHMCL's manual "Screening Sheet" format: a grouped
# two-row header (Essential Qualification / Desirable Qualification /
# Essential Experience / Preferred Experience sections, each with
# possessed / fulfilled / documents-attached sub-columns, plus a
# Certifications-from-CV section: every certificate the CV mentions and
# one row per candidate, in the same
# order as the uploaded roster Excel.
# ---------------------------------------------------------------------------

_YES_NO = {True: "Yes", False: "No"}


def _parse_dob(dob: Optional[str]) -> Optional[date]:
    if not dob:
        return None
    text = dob.strip()[:19]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _age_from_dob(dob: Optional[str]) -> Optional[int]:
    parsed = _parse_dob(dob)
    if parsed is None:
        return None
    today = date.today()
    return today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))


def _excel_field(candidate: Candidate, *keys: str) -> str:
    """Joins non-empty roster columns (e.g. course name + specialization)."""
    data = candidate.raw_excel_data or {}
    parts = []
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in ("nan", "n/a", "na", "none"):
            parts.append(text)
    return " - ".join(parts)


def _fulfilled(evals: list[CriterionEvaluation]) -> str:
    """Collapses a group of criterion results into Yes / No / Needs review."""
    if not evals:
        return "—"
    if any(e.result == "fail" for e in evals):
        return "No"
    if any(e.result == "needs_review" for e in evals):
        return "Needs review"
    return "Yes"


def _docs_attached(evals: list[CriterionEvaluation]) -> str:
    if not evals:
        return "—"
    return _YES_NO[all(e.citation_document for e in evals)]


def _certifications_text(candidate: Candidate) -> str:
    """
    "Certificates mentioned in CV" column: every certificate Gemini found
    in the CV, one per line, with issuer/year when stated. Distinguishes
    "not extracted" (not screened, or no readable CV) from "CV lists none".
    """
    certs = candidate.cv_certifications
    if certs is None:
        return "—" if candidate.status == "not_evaluated" else "No readable CV provided"
    if not certs:
        return "None mentioned in CV"
    lines = []
    for cert in certs:
        name = cert.get("name") or ""
        extras = [x for x in (cert.get("issuer"), cert.get("year")) if x]
        lines.append(f"{name} ({', '.join(extras)})" if extras else name)
    return "\n".join(lines)


def _total_exp_text(evals: list[CriterionEvaluation]) -> str:
    """Pulls the computed total ("total = 7.7 yrs") out of the evaluation
    reasoning when present; falls back to the match percentage."""
    for e in evals:
        # The final total is stated last in the reasoning ("... total = 7.7
        # yrs >= 5 required"), after the per-organization sub-totals -- so
        # take the LAST match, not the first.
        matches = re.findall(r"total[^=\n]*=\s*~?([\d.]+)\s*(?:yrs|years)", e.reasoning or "", re.IGNORECASE)
        if matches:
            return f"~{matches[-1]} yrs"
    for e in evals:
        if e.match_percentage is not None:
            return f"{e.match_percentage}% of required"
    return "—"


@router.get("/export")
def export_results(
    profile_id: str,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    sort: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Pass ?sort=skill_match to rank best-first instead of roster order.

    Exports candidates as an IHMCL-style Screening Sheet, in upload
    (roster Excel) order. Pass ?status=... to export just one bucket
    and/or ?run_id=... to export one screening run's candidates.
    """
    profile = _get_profile_or_404(profile_id, db)

    all_candidates = (
        db.query(Candidate)
        .filter(Candidate.job_profile_id == profile_id)
        .order_by(Candidate.roster_position, Candidate.created_at)
        .all()
    )
    if run_id is not None:
        all_candidates = [c for c in all_candidates if c.last_screening_run_id == run_id]
    export_candidates = all_candidates if status is None else [c for c in all_candidates if c.status == status]
    if _wants_ranking(sort, profile):
        _attach_skill_match(db, export_candidates)
        export_candidates = _rank_candidates(export_candidates)

    evaluations = (
        db.query(CriterionEvaluation)
        .options(joinedload(CriterionEvaluation.criterion))
        .filter(CriterionEvaluation.candidate_id.in_([c.id for c in export_candidates] or [""]))
        .all()
    )
    evals_by_candidate: dict[str, list[CriterionEvaluation]] = {}
    for e in evaluations:
        evals_by_candidate.setdefault(e.candidate_id, []).append(e)

    wb = Workbook()
    ws = wb.active
    ws.title = "Screening Sheet"

    # -- Header (rows 1-2) --------------------------------------------------
    # (col, group title or None, sub header, width)
    single_columns = [
        ("A", "S No.", 6),
        ("B", "Application No.", 20),
        ("C", "Applicant Name", 24),
        ("D", "Date of Birth", 14),
        ("E", "Age", 7),
        ("F", "Whether supporting documents attached (Yes/No)", 16),
        ("G", "Category", 10),
        ("H", "Graduation", 26),
        ("I", "Post Graduation", 26),
    ]
    groups = [
        ("Essential Qualification", [
            ("J", "Qualification possessed", 28),
            ("K", "Whether Fulfilled (Yes/No)", 14),
            ("L", "Whether supporting documents attached (Yes/No)", 16),
        ]),
        ("Desirable Qualification", [
            ("M", "Qualification possessed", 28),
            ("N", "Whether Fulfilled (Yes/No)", 14),
            ("O", "Whether supporting documents attached (Yes/No)", 16),
        ]),
        ("Essential Experience", [
            ("P", "Total Exp.", 14),
            ("Q", "Relevant Experience", 18),
            ("R", "Experience Fulfilled (Yes/No)", 14),
            ("S", "Whether supporting documents attached (Yes/No)", 16),
        ]),
        ("Preferred Experience / Skills", [
            ("T", "Skills & experience possessed", 40),
            ("U", "Match %", 10),
            ("V", "Gist", 50),
        ]),
        ("Certifications (from CV)", [
            ("W", "Certificates mentioned in CV", 40),
        ]),
    ]
    tail_columns = [
        ("X", "Eligible/Not Eligible", 18),
        ("Y", "Document Remarks", 30),
        ("Z", "Remarks", 40),
    ]

    header_font = Font(bold=True, size=10)
    header_fill = PatternFill("solid", fgColor="D9E2F3")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    body_align = Alignment(vertical="top", wrap_text=True)
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def _header_cell(coordinate: str, value: str):
        cell = ws[coordinate]
        cell.value = value
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border

    for col, title, width in single_columns + tail_columns:
        ws.merge_cells(f"{col}1:{col}2")
        _header_cell(f"{col}1", title)
        ws[f"{col}2"].border = border
        ws.column_dimensions[col].width = width

    for group_title, subs in groups:
        first, last = subs[0][0], subs[-1][0]
        ws.merge_cells(f"{first}1:{last}1")
        _header_cell(f"{first}1", group_title)
        for col, sub_title, width in subs:
            ws[f"{col}1"].border = border
            _header_cell(f"{col}2", sub_title)
            ws.column_dimensions[col].width = width

    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 42
    ws.freeze_panes = "A3"

    # -- Data rows ------------------------------------------------------------
    status_text = {
        "eligible": "Eligible",
        "not_eligible": "Not Eligible",
        "needs_review": "Needs Review",
        "not_evaluated": "Not Screened",
    }
    docs_text = {
        "documents_complete": "Yes",
        "documents_incomplete": "Partial",
    }

    for idx, c in enumerate(export_candidates, start=1):
        evals = evals_by_candidate.get(c.id, [])
        edu_essential = [e for e in evals if e.criterion.type == "education" and e.criterion.is_essential]
        edu_desirable = [e for e in evals if e.criterion.type == "education" and not e.criterion.is_essential]
        exp_essential = [e for e in evals if e.criterion.type == "experience" and e.criterion.is_essential]
        skill_evals = [e for e in evals if e.criterion.type == "skill"]

        graduation = _excel_field(c, "G Course Name", "G Specialization") or _excel_field(
            c, "Graduation Degree", "Graduation Subject"
        )
        post_grad = _excel_field(c, "P Course Name", "P Specialization")
        other_qual = _excel_field(c, "O Course Name")
        qualifications = "; ".join(p for p in (graduation, post_grad, other_qual) if p)

        exp_pct = next((e.match_percentage for e in exp_essential if e.match_percentage is not None), None)
        skill_pct = next((e.match_percentage for e in skill_evals if e.match_percentage is not None), None)
        exp_gist = next((e.reasoning for e in exp_essential if e.reasoning), "")

        failed = sorted({e.criterion.type for e in evals if e.result == "fail" and e.criterion.is_essential})
        review = sorted({e.criterion.type for e in evals if e.result == "needs_review" and e.criterion.is_essential})
        if c.status == "eligible":
            remarks = "Meets all essential criteria"
        elif c.status == "not_eligible":
            remarks = f"Not eligible — fails essential: {', '.join(failed)}" if failed else "Not eligible"
        elif c.status == "needs_review":
            remarks = f"Manual review needed: {', '.join(review)}" if review else "Manual review needed"
        else:
            remarks = "Screening not run yet"
        if c.review_note and (c.status == "needs_review" or c.review_tag == "close_miss"):
            remarks += f" — {c.review_note}"
        if c.gov_tag:
            remarks += " — Government relevant experience"
        if c.status_overridden:
            remarks += f" (status set manually by HR{': ' + c.override_reason if c.override_reason else ''})"

        doc_remarks = []
        if c.resume_fetch_status is not None:
            # Roster-only candidate: the sheet row is the evidence; say what
            # became of the resume.
            if c.resume_fetch_status == "failed":
                doc_remarks.append(f"Resume not retrieved: {c.resume_fetch_error or 'unknown reason'}")
            elif c.resume_fetch_status == "no_link":
                doc_remarks.append("No resume link in the roster")
            elif c.resume_fetch_status != "fetched":
                doc_remarks.append("Resume not fetched (screened from the roster row only)")
        elif c.ingestion_status != "documents_complete":
            doc_remarks.append(f"Documents: {c.ingestion_status.replace('_', ' ')}")
        uncited = sorted({
            e.criterion.type
            for e in evals
            if not e.citation_document and e.criterion.type not in ("age", "skill")
        })
        if uncited:
            doc_remarks.append(f"No supporting document cited for: {', '.join(uncited)}")

        row = [
            idx,
            c.external_id,
            c.name or "",
            c.dob or "",
            _age_from_dob(c.dob) or _excel_field(c, "Age") or "",
            "Resume" if c.resume_fetch_status == "fetched" else docs_text.get(c.ingestion_status, "No"),
            c.normalized_category or c.raw_category or "",
            graduation,
            post_grad,
            qualifications,
            _fulfilled(edu_essential),
            _docs_attached(edu_essential),
            post_grad or other_qual,
            _fulfilled(edu_desirable),
            _docs_attached(edu_desirable),
            _total_exp_text(exp_essential),
            f"{exp_pct}% of required" if exp_pct is not None else "—",
            _fulfilled(exp_essential),
            _docs_attached(exp_essential),
            next((e.reasoning for e in skill_evals if e.reasoning), ""),
            f"{skill_pct}%" if skill_pct is not None else "—",
            exp_gist,
            _certifications_text(c),
            status_text.get(c.status, c.status),
            "; ".join(doc_remarks),
            remarks,
        ]
        row_num = idx + 2
        for col_num, value in enumerate(row, start=1):
            cell = ws.cell(row=row_num, column=col_num, value=value)
            cell.alignment = body_align
            cell.border = border
            cell.font = Font(size=10)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    safe_title = "".join(ch if ch.isalnum() else "_" for ch in profile.title)[:50]
    filename = f"Screening_Sheet_{safe_title}_{date.today().strftime('%d.%m.%Y')}.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
