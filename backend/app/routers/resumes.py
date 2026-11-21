"""
Candidate uploads that need no department template. HR picks one of:

  roster only        POST upload-roster          sheet with resume links
  resumes ZIP only   POST upload-resumes         no sheet: every resume is a
                                                 candidate and is the whole
                                                 truth about them
  roster + ZIP       POST upload-roster-resumes  sheet (e.g. a Google Form
                                                 export) plus a ZIP of
                                                 resumes, matched to rows by
                                                 name / email / phone

Roster-only flow (no per-candidate documents ZIP required):

  1. POST  upload-roster    sheet only -> candidates, screenable right away
  2. (HR runs the normal batch screening: the sheet row alone is the evidence)
  3. POST  fetch-resumes    downloads the resume ONLY for shortlisted
                            candidates (eligible / needs review), then
                            re-screens each with their resume
  4. POST  resumes-zip      optional fallback for links that can't be
                            downloaded: PDFs matched to candidates by the
                            name / email / phone in the file name
"""

import os
import re
import shutil
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models.candidate import Candidate, CandidateDocument
from app.models.job_profile import JobProfile
from app.routers.candidates import UPLOAD_DIR, _delete_candidate_screening_data
from app.schemas.candidate import CandidateUploadSummary
from app.services.auth_service import get_current_hr_user
from app.services.candidate_ingestion import process_resume_zip
from app.services.candidate_evaluation import evaluate_candidate
from app.services.resume_fetcher import ResumeFetchError, fetch_resume_pdf
from app.services.roster_ingestion import parse_roster

router = APIRouter(
    prefix="/jd/profiles/{profile_id}/candidates",
    tags=["roster"],
    dependencies=[Depends(get_current_hr_user)],
)

# Candidates the first (sheet-only) screening shortlisted -- the only ones
# whose resume is worth downloading.
SHORTLISTED = ("eligible", "needs_review")


def _get_profile(db: Session, profile_id: str) -> JobProfile:
    profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Job Profile '{profile_id}' not found")
    return profile


def _save_upload(upload: UploadFile, batch_dir: str) -> str:
    """Streams an uploaded file into batch_dir (multi-GB ZIPs must not be
    read into memory) and returns its path."""
    path = os.path.join(batch_dir, os.path.basename(upload.filename or "upload"))
    with open(path, "wb") as f:
        shutil.copyfileobj(upload.file, f, length=1024 * 1024)
    return path


def _new_batch_dir() -> str:
    batch_dir = os.path.join(UPLOAD_DIR, str(uuid.uuid4()))
    os.makedirs(batch_dir, exist_ok=True)
    return batch_dir


def _reset_for_reupload(db: Session, candidate: Candidate) -> None:
    """The same candidate uploaded again: old results, override and
    documents go -- they belonged to the previous upload."""
    _delete_candidate_screening_data(db, candidate.id)
    candidate.computed_status = None
    candidate.status = "not_evaluated"
    candidate.status_overridden = False
    candidate.override_reason = None
    candidate.overridden_by = None
    candidate.overridden_at = None
    candidate.cv_certifications = None
    candidate.has_cyber_security_certification = None
    candidate.resume_consistency = None
    candidate.gov_experience, candidate.gov_relevant_experience = None, None
    candidate.documents.clear()


def _upsert_candidates(
    db: Session, profile: JobProfile, rows: list[tuple[str, dict]]
) -> tuple[list[Candidate], int]:
    """(external_id, fields) per candidate -> created/replaced Candidate rows
    (flushed, not committed) and how many replaced an existing record."""
    existing_by_id: dict[str, list[Candidate]] = {}
    for c in (
        db.query(Candidate)
        .filter(Candidate.job_profile_id == profile.id)
        .order_by(Candidate.roster_position, Candidate.created_at)
        .all()
    ):
        existing_by_id.setdefault(c.external_id, []).append(c)

    candidates: list[Candidate] = []
    replaced = 0
    for external_id, fields in rows:
        found = existing_by_id.get(external_id)
        if found:
            # Same candidate re-uploaded: replace their record and wipe the
            # old results/resume, exactly like the ZIP upload does.
            candidate = found[0]
            for duplicate in found[1:]:
                _delete_candidate_screening_data(db, duplicate.id)
                db.delete(duplicate)
            _reset_for_reupload(db, candidate)
            for key, value in fields.items():
                setattr(candidate, key, value)
            replaced += 1
        else:
            candidate = Candidate(job_profile_id=profile.id, external_id=external_id, **fields)
            db.add(candidate)
        candidates.append(candidate)
    db.flush()
    return candidates, replaced


def _blank_screening_fields() -> dict:
    return dict(review_tag=None, review_note=None, suitability_score=None, competency_scores=None)


def _ingest_roster(db: Session, profile: JobProfile, excel_path: str) -> tuple[list[Candidate], int]:
    """Parses the sheet and upserts one roster_only candidate per row."""
    try:
        rows = parse_roster(excel_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse the candidate data file: {e}")

    # Roster candidates are judged on the sheet row (+ resume); no
    # department template is involved.
    profile.department_template_id = None

    return _upsert_candidates(db, profile, [
        (r["external_id"], dict(
            name=r["name"],
            roster_position=r["roster_position"],
            email=r["email"],
            phone=r["phone"],
            dob=r["dob"],
            gender=r["gender"],
            raw_category=r["raw_category"],
            normalized_category=r["normalized_category"],
            raw_excel_data=r["raw_excel_data"],
            ingestion_status="roster_only",
            resume_link=r["resume_link"],
            resume_fetch_status="pending" if r["resume_link"] else "no_link",
            resume_fetch_error=None,
            **_blank_screening_fields(),
        ))
        for r in rows
    ])


@router.post("/upload-roster", response_model=CandidateUploadSummary)
def upload_roster(
    profile_id: str,
    excel_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Sheet-only upload. Plain `def` so parsing runs on a worker thread."""
    profile = _get_profile(db, profile_id)
    excel_path = _save_upload(excel_file, _new_batch_dir())
    candidates, replaced = _ingest_roster(db, profile, excel_path)

    db.commit()
    for c in candidates:
        db.refresh(c)

    return CandidateUploadSummary(
        job_profile_id=profile.id,
        total_candidates_found=len(candidates),
        replaced_candidates=replaced,
        # Nothing is "incomplete": every row is screenable from the sheet.
        documents_complete=len(candidates),
        documents_incomplete=0,
        no_documents_found=0,
        excel_row_not_found=0,
        corrupt_zip=0,
        candidates=candidates,
    )


@router.post("/upload-resumes", response_model=CandidateUploadSummary)
def upload_resumes_only(
    profile_id: str,
    resumes_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    No roster: a ZIP of resumes (loose PDF/DOCX files, or one folder per
    candidate). Every resume becomes a candidate and is the WHOLE truth
    about them -- there is no sheet to compare it with. Screening makes a
    Gemini call per resume, which also reads the name, contact details and
    date of birth from it.
    """
    profile = _get_profile(db, profile_id)
    batch_dir = _new_batch_dir()
    zip_path = _save_upload(resumes_zip, batch_dir)

    try:
        results = process_resume_zip(zip_path, os.path.join(batch_dir, "documents"))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid ZIP.")
    if not results:
        raise HTTPException(status_code=422, detail="No PDF or Word (.docx) resumes were found in the ZIP.")

    profile.department_template_id = None
    candidates, replaced = _upsert_candidates(db, profile, [
        (r["external_id"], dict(
            name=r["name"],
            roster_position=position,
            email=None,
            phone=None,
            dob=None,
            gender=None,
            raw_category=None,
            normalized_category=None,
            raw_excel_data=None,
            ingestion_status=r["ingestion_status"],
            resume_link=None,
            resume_fetch_status=None,
            resume_fetch_error=None,
            **_blank_screening_fields(),
        ))
        for position, r in enumerate(results, start=1)
    ])

    for candidate, r in zip(candidates, results):
        for doc_type, local_path in r["matched_documents"].items():
            readable = local_path.lower().endswith((".pdf", ".docx"))
            db.add(CandidateDocument(
                candidate_id=candidate.id,
                document_type=doc_type,
                file_path=local_path,
                original_filename=os.path.basename(local_path),
                extracted_text=None if readable else "",  # read at screening time
            ))

    db.commit()
    for c in candidates:
        db.refresh(c)

    with_resume = sum(1 for r in results if r["ingestion_status"] == "resume_only")
    return CandidateUploadSummary(
        job_profile_id=profile.id,
        total_candidates_found=len(candidates),
        replaced_candidates=replaced,
        documents_complete=with_resume,
        documents_incomplete=0,
        no_documents_found=len(results) - with_resume,
        excel_row_not_found=0,
        corrupt_zip=0,
        candidates=candidates,
    )


@router.post("/upload-roster-resumes", response_model=CandidateUploadSummary)
def upload_roster_with_resumes(
    profile_id: str,
    excel_file: UploadFile = File(...),
    resumes_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Roster (e.g. a Google Form export) + a ZIP of resumes in one go. Each
    resume is matched to its row by the email, phone or full name in the
    file name. Matched candidates are screened on the row with the resume
    alongside (a sheet-vs-resume mismatch is flagged); unmatched rows are
    screened on the row alone and can still have their resume fetched from
    a link in the sheet later.
    """
    profile = _get_profile(db, profile_id)
    batch_dir = _new_batch_dir()
    excel_path = _save_upload(excel_file, batch_dir)
    zip_path = _save_upload(resumes_zip, batch_dir)

    candidates, replaced = _ingest_roster(db, profile, excel_path)
    try:
        matched, unmatched = _attach_resumes_from_zip(db, zip_path, candidates)
    except zipfile.BadZipFile:
        db.rollback()
        raise HTTPException(status_code=422, detail="The uploaded resumes file is not a valid ZIP.")

    db.commit()
    for c in candidates:
        db.refresh(c)

    return CandidateUploadSummary(
        job_profile_id=profile.id,
        total_candidates_found=len(candidates),
        replaced_candidates=replaced,
        documents_complete=len(candidates),
        documents_incomplete=0,
        no_documents_found=0,
        excel_row_not_found=0,
        corrupt_zip=0,
        resumes_matched=len(matched),
        unmatched_files=unmatched,
        candidates=candidates,
    )


def _store_resume(db: Session, candidate: Candidate, source_path: str, filename: str) -> None:
    """Records `source_path` as the candidate's resume (replacing any old one)."""
    for old in [d for d in candidate.documents if d.document_type == "resume_cv"]:
        candidate.documents.remove(old)
    db.add(CandidateDocument(
        candidate_id=candidate.id,
        document_type="resume_cv",
        file_path=source_path,
        original_filename=filename,
        extracted_text=None,  # extracted (with OCR fallback) at screening time
    ))
    candidate.ingestion_status = "documents_complete"
    candidate.resume_fetch_status = "fetched"
    candidate.resume_fetch_error = None


def _mark_resume_unavailable(candidate: Candidate, reason: str) -> None:
    """A shortlisted candidate whose resume can't be had goes to HR review --
    the sheet-only result stands but is no longer trusted blindly."""
    candidate.resume_fetch_status = "failed"
    candidate.resume_fetch_error = reason[:500]
    if candidate.status == "eligible":
        candidate.status = "needs_review"
    if candidate.status == "needs_review" and candidate.review_tag in (None, "awaiting_resume"):
        candidate.review_tag = "resume_unavailable"
        candidate.review_note = f"Resume not retrieved: {reason}"[:500]


def _rescreen_with_resume(db: Session, candidate: Candidate, profile_id: str) -> None:
    profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
    if profile is None:
        return
    try:
        evaluate_candidate(db, candidate, profile)
        db.commit()
    except Exception:
        # Gemini hiccup: keep the stored resume and the earlier result; HR
        # can re-screen this candidate from the Results screen.
        db.rollback()


def _fetch_one_resume(profile_id: str, candidate_id: str) -> None:
    """Worker for one candidate; owns its DB session (sessions aren't
    thread-safe)."""
    db = SessionLocal()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if candidate is None:
            return
        try:
            if not candidate.resume_link:
                _mark_resume_unavailable(candidate, "The sheet has no resume link for this candidate.")
                db.commit()
                return

            destination = os.path.join(UPLOAD_DIR, "resumes", candidate.id, "resume.pdf")
            try:
                fetch_resume_pdf(candidate.resume_link, destination)
            except ResumeFetchError as e:
                _mark_resume_unavailable(candidate, str(e))
                db.commit()
                return

            _store_resume(db, candidate, destination, "resume.pdf")
            db.commit()
            _rescreen_with_resume(db, candidate, profile_id)
        except Exception as e:
            db.rollback()
            candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
            if candidate is not None:
                _mark_resume_unavailable(candidate, f"Unexpected error: {type(e).__name__}: {e}")
                db.commit()
    finally:
        db.close()


def _run_resume_fetches(profile_id: str, candidate_ids: list[str]) -> None:
    workers = max(1, int(os.getenv("RESUME_FETCH_CONCURRENCY", "6")))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for future in [executor.submit(_fetch_one_resume, profile_id, cid) for cid in candidate_ids]:
            try:
                future.result()
            except Exception:
                pass


@router.post("/fetch-resumes")
def fetch_resumes(
    profile_id: str,
    background_tasks: BackgroundTasks,
    retry_failed: bool = False,
    db: Session = Depends(get_db),
):
    """
    Starts downloading resumes in the background for SHORTLISTED candidates
    (screened eligible / needs review) whose resume is still pending --
    also the failed ones with retry_failed=true. Each download is followed
    by a re-screen that includes the resume. Poll GET fetch-resumes/status.
    """
    _get_profile(db, profile_id)

    wanted = ["pending", "failed"] if retry_failed else ["pending", "no_link"]
    candidates = (
        db.query(Candidate)
        .filter(
            Candidate.job_profile_id == profile_id,
            Candidate.status.in_(SHORTLISTED),
            Candidate.resume_fetch_status.in_(wanted),
        )
        .all()
    )
    for c in candidates:
        c.resume_fetch_status = "fetching"
    db.commit()

    if candidates:
        background_tasks.add_task(_run_resume_fetches, profile_id, [c.id for c in candidates])
    return {"queued": len(candidates)}


@router.get("/fetch-resumes/status")
def fetch_resumes_status(profile_id: str, db: Session = Depends(get_db)):
    """Counts per resume_fetch_status, plus how many shortlisted candidates
    still wait for a fetch -- powers the progress line in the UI."""
    _get_profile(db, profile_id)

    counts = dict(
        db.query(Candidate.resume_fetch_status, func.count(Candidate.id))
        .filter(Candidate.job_profile_id == profile_id, Candidate.resume_fetch_status.isnot(None))
        .group_by(Candidate.resume_fetch_status)
        .all()
    )
    shortlisted_waiting = (
        db.query(func.count(Candidate.id))
        .filter(
            Candidate.job_profile_id == profile_id,
            Candidate.status.in_(SHORTLISTED),
            Candidate.resume_fetch_status.in_(["pending", "no_link"]),
        )
        .scalar()
    )
    return {
        "pending": counts.get("pending", 0),
        "fetching": counts.get("fetching", 0),
        "fetched": counts.get("fetched", 0),
        "failed": counts.get("failed", 0),
        "no_link": counts.get("no_link", 0),
        "shortlisted_waiting": shortlisted_waiting,
    }


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt"}


def _name_tokens(name: str | None) -> list[str]:
    parts = [p for p in re.split(r"[^a-z]+", (name or "").lower()) if len(p) > 1 and p not in _TITLES]
    return parts


def _match_candidate(stem: str, candidates: list[Candidate]) -> Candidate | None:
    """The one candidate whose email, phone or full name appears in the file
    name; None when nothing matches or several do (ambiguous -> reported)."""
    flat = _alnum(stem)
    digits = re.sub(r"\D", "", stem)
    hits = []
    for c in candidates:
        email = (c.email or "").lower()
        phone = re.sub(r"\D", "", c.phone or "")
        tokens = _name_tokens(c.name)
        if (
            (email and (_alnum(email) in flat or _alnum(email.split("@")[0]) == flat))
            or (len(phone) >= 10 and phone[-10:] in digits)
            or (len(tokens) >= 2 and tokens[0] in flat and tokens[-1] in flat)
        ):
            hits.append(c)
    return hits[0] if len(hits) == 1 else None


@router.post("/resumes-zip")
def upload_resumes_zip(
    profile_id: str,
    background_tasks: BackgroundTasks,
    resumes_zip: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Fallback for resume links that can't be downloaded: a ZIP (or any mix of
    folders) of resume PDFs, each matched to a candidate by the email, phone
    or full name found in its file name. Matched candidates are re-screened
    with their resume in the background; the rest are listed in the response.
    """
    _get_profile(db, profile_id)

    batch_dir = os.path.join(UPLOAD_DIR, "resumes_zip", str(uuid.uuid4()))
    os.makedirs(batch_dir, exist_ok=True)
    zip_path = os.path.join(batch_dir, "resumes.zip")
    with open(zip_path, "wb") as f:
        shutil.copyfileobj(resumes_zip.file, f, length=1024 * 1024)

    candidates = db.query(Candidate).filter(Candidate.job_profile_id == profile_id).all()
    try:
        matched, unmatched = _attach_resumes_from_zip(db, zip_path, candidates)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid ZIP.")

    db.commit()
    if matched:
        background_tasks.add_task(_rescreen_candidates, profile_id, matched)
    return {"matched": len(matched), "unmatched_files": unmatched}


def _attach_resumes_from_zip(
    db: Session, zip_path: str, candidates: list[Candidate]
) -> tuple[list[str], list[str]]:
    """Stores each PDF/DOCX in the ZIP as the resume of the one candidate
    whose email, phone or full name is in its file name. Returns (matched
    candidate ids, file names that matched nobody or were ambiguous).
    Raises zipfile.BadZipFile for a broken ZIP."""
    matched: list[str] = []
    unmatched: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.namelist():
            norm = entry.replace("\\", "/")
            filename = os.path.basename(norm)
            if not filename or "__MACOSX" in norm or filename.startswith("."):
                continue
            if not filename.lower().endswith((".pdf", ".docx")):
                continue
            candidate = _match_candidate(os.path.splitext(filename)[0], candidates)
            if candidate is None or candidate.id in seen:
                unmatched.append(filename)
                continue
            seen.add(candidate.id)

            extension = os.path.splitext(filename)[1].lower()
            target = os.path.join(UPLOAD_DIR, "resumes", candidate.id, f"resume{extension}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(entry) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            _store_resume(db, candidate, target, filename)
            matched.append(candidate.id)
    return matched, unmatched


def _rescreen_candidates(profile_id: str, candidate_ids: list[str]) -> None:
    workers = max(1, int(os.getenv("RESUME_FETCH_CONCURRENCY", "6")))

    def one(candidate_id: str) -> None:
        db = SessionLocal()
        try:
            candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
            if candidate is not None:
                _rescreen_with_resume(db, candidate, profile_id)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for future in [executor.submit(one, cid) for cid in candidate_ids]:
            try:
                future.result()
            except Exception:
                pass
