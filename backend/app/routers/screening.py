"""
Screening endpoints -- single-candidate evaluation, plus batch screening
with live progress tracking.

Candidates whose documents are missing/incomplete are skipped (not sent to
Gemini at all) -- this matches the requirement that missing documents
shouldn't waste an LLM call and should be tracked separately from genuine
evaluation failures. If one candidate's processing fails unexpectedly for
any other reason, the whole batch does not stop -- only that candidate is
marked "not_evaluated".
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.session import get_db, SessionLocal
from app.models.job_profile import JobProfile
from app.models.candidate import Candidate
from app.models.screening_run import ScreeningRun
from app.schemas.screening import CandidateEvaluationResult, ScreeningRunOut
from app.services.candidate_evaluation import (
    SCREENABLE_STATUSES,
    criteria_fingerprint,
    evaluate_candidate,
    results_outdated,
)
from app.services.gemini_service import GeminiParsingError
from app.services.auth_service import get_current_hr_user

logger = logging.getLogger("uvicorn.error")

single_router = APIRouter(
    prefix="/jd/profiles/{profile_id}/candidates/{candidate_id}",
    tags=["screening"],
    dependencies=[Depends(get_current_hr_user)],
)

batch_router = APIRouter(
    prefix="/jd/profiles/{profile_id}",
    tags=["screening"],
    dependencies=[Depends(get_current_hr_user)],
)


@single_router.post("/evaluate", response_model=CandidateEvaluationResult)
def evaluate_single_candidate(profile_id: str, candidate_id: str, db: Session = Depends(get_db)):
    profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Job Profile '{profile_id}' not found")

    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id, Candidate.job_profile_id == profile_id)
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate '{candidate_id}' not found in this profile")

    if candidate.ingestion_status not in SCREENABLE_STATUSES:
        # Skip evaluation entirely -- don't waste a Gemini call on a
        # candidate whose documents we already know are missing/broken.
        candidate.status = "not_evaluated"
        candidate.computed_status = None
        candidate.status_overridden = False
        candidate.override_reason = None
        candidate.overridden_by = None
        candidate.overridden_at = None
        db.commit()
        return CandidateEvaluationResult(
            candidate_id=candidate.id,
            ingestion_status=candidate.ingestion_status,
            status=candidate.status,
            skipped=True,
            skip_reason=(
                f"Document ingestion is at status '{candidate.ingestion_status}' -- "
                f"evaluation was skipped. Please resolve the document issue first."
            ),
        )

    # Surface failures as readable messages instead of a bare 500 -- the
    # batch path has its own safety net, but this endpoint reports straight
    # back to the UI, so HR should see WHY a screening attempt failed.
    try:
        evaluations = evaluate_candidate(db, candidate, profile)
    except GeminiParsingError as e:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"Screening failed while calling Gemini: {e}",
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Screening failed unexpectedly ({type(e).__name__}): {e}",
        )
    db.commit()

    for e in evaluations:
        db.refresh(e)

    return CandidateEvaluationResult(
        candidate_id=candidate.id,
        ingestion_status=candidate.ingestion_status,
        status=candidate.status,
        skipped=False,
        cv_certifications=candidate.cv_certifications,
        has_cyber_security_certification=candidate.has_cyber_security_certification,
        resume_consistency=candidate.resume_consistency,
        evaluations=evaluations,
    )


def _increment_run_counters(db: Session, run_id: str, failed: bool = False) -> None:
    """
    Atomic SQL increments -- multiple worker threads update the same
    ScreeningRun row concurrently, so read-modify-write on an ORM object
    would lose counts.
    """
    values = {ScreeningRun.processed_count: ScreeningRun.processed_count + 1}
    if failed:
        values[ScreeningRun.failed_count] = ScreeningRun.failed_count + 1
    db.query(ScreeningRun).filter(ScreeningRun.id == run_id).update(values)
    db.commit()


def _screen_one_candidate(run_id: str, profile_id: str, candidate_id: str) -> None:
    """
    Worker for one candidate. Runs on a thread-pool thread, so it needs its
    OWN database session -- SQLAlchemy sessions are not thread-safe.
    """
    db = SessionLocal()
    try:
        # HR pressed Stop: candidates not yet started are skipped and keep
        # their previous result (and run tag) untouched. Ones already
        # mid-evaluation can't be interrupted and finish normally.
        run_status = db.query(ScreeningRun.status).filter(ScreeningRun.id == run_id).scalar()
        if run_status != "running":
            return

        candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
        if candidate is None:
            _increment_run_counters(db, run_id)
            return

        try:
            if candidate.ingestion_status not in SCREENABLE_STATUSES:
                candidate.status = "not_evaluated"
                candidate.computed_status = None
                candidate.status_overridden = False
                candidate.override_reason = None
                candidate.overridden_by = None
                candidate.overridden_at = None
            else:
                profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
                evaluate_candidate(db, candidate, profile)
            # Tag the candidate with this run (skipped candidates too --
            # they were part of the batch, so "show only this screening"
            # must include them).
            candidate.last_screening_run_id = run_id
            db.commit()
            _increment_run_counters(db, run_id)
        except Exception:
            logger.exception("Screening failed for candidate %s (run %s)", candidate_id, run_id)
            # A single candidate's failure must never stop the batch --
            # roll back any partial changes for this candidate, mark
            # them not_evaluated, and let the other workers continue.
            db.rollback()
            candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
            if candidate is not None:
                candidate.status = "not_evaluated"
                candidate.last_screening_run_id = run_id
                db.commit()
            _increment_run_counters(db, run_id, failed=True)
    finally:
        db.close()


def _run_batch_screening(run_id: str, profile_id: str, candidate_ids: list[str]) -> None:
    """
    Runs in the background, after the POST /screen request has already
    returned to the caller. Candidates are screened CONCURRENTLY on a
    small thread pool (each candidate is one Gemini call + DB writes, all
    independent of each other) -- SCREENING_CONCURRENCY in .env controls
    the worker count.
    """
    workers = max(1, int(os.getenv("SCREENING_CONCURRENCY", "4")))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_screen_one_candidate, run_id, profile_id, candidate_id)
            for candidate_id in candidate_ids
        ]
        for future in futures:
            # Per-candidate failures are already handled inside the worker;
            # anything surfacing here is unexpected (e.g. DB down) and must
            # not stop the run from being marked completed.
            try:
                future.result()
            except Exception:
                pass

    db = SessionLocal()
    try:
        run = db.query(ScreeningRun).filter(ScreeningRun.id == run_id).first()
        if run is not None:
            run.status = "stopped" if run.status == "stopping" else "completed"
            run.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@batch_router.post("/screen", response_model=ScreeningRunOut)
def start_batch_screening(
    profile_id: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
    run_id: Optional[str] = None,
    outdated: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_hr_user),
):
    """
    Starts screening every eligible candidate for a profile in the
    background, and returns immediately with a run_id. Poll
    GET /jd/profiles/{profile_id}/screening-runs/{run_id} for live progress.

    By default, only candidates still at status="not_evaluated" are
    screened (so re-calling this doesn't waste Gemini calls re-evaluating
    people who already have a result). Pass force=true to re-evaluate
    everyone regardless of current status (e.g. after editing criteria).
    Pass run_id=<screening run id> to restrict either mode to only the
    candidates last screened in that run -- they'll be tagged with the
    NEW run this call creates. Pass outdated=true to re-screen only
    candidates whose result was produced under criteria that have since
    been edited (combinable with run_id).
    """
    profile = db.query(JobProfile).filter(JobProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=f"Job Profile '{profile_id}' not found")

    query = db.query(Candidate).filter(Candidate.job_profile_id == profile_id)
    if run_id is not None:
        query = query.filter(Candidate.last_screening_run_id == run_id)
    if outdated:
        fingerprint = criteria_fingerprint(profile)
        candidates = [c for c in query.all() if results_outdated(c, fingerprint)]
    else:
        if not force:
            query = query.filter(Candidate.status == "not_evaluated")
        candidates = query.all()

    run = ScreeningRun(
        job_profile_id=profile_id,
        total_candidates=len(candidates),
        processed_count=0,
        failed_count=0,
        status="running",
        started_by=current_user.id,
        candidate_ids=[c.id for c in candidates],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    candidate_ids = [c.id for c in candidates]
    background_tasks.add_task(_run_batch_screening, run.id, profile_id, candidate_ids)

    return run


def _remaining_candidate_ids(db: Session, run: ScreeningRun) -> Optional[list[str]]:
    """
    Candidates a stopped (or crashed) run never reached, still in the
    profile -- what "Continue" screens. None when the run can't be
    continued: it isn't stopped/failed, predates scope tracking, or a newer
    run has started since (that one may have re-screened them already).
    """
    if run.status not in ("stopped", "failed") or not run.candidate_ids:
        return None
    newer = (
        db.query(ScreeningRun.id)
        .filter(ScreeningRun.job_profile_id == run.job_profile_id, ScreeningRun.started_at > run.started_at)
        .first()
    )
    if newer:
        return None
    remaining = [
        cid for (cid,) in db.query(Candidate.id).filter(
            Candidate.id.in_(run.candidate_ids),
            Candidate.job_profile_id == run.job_profile_id,
            or_(Candidate.last_screening_run_id.is_(None), Candidate.last_screening_run_id != run.id),
        )
    ]
    return remaining or None


def _run_out(db: Session, run: ScreeningRun, **extra) -> ScreeningRunOut:
    remaining = _remaining_candidate_ids(db, run)
    return ScreeningRunOut.model_validate(run).model_copy(
        update={"remaining_candidates": len(remaining) if remaining else None, **extra}
    )


@batch_router.get("/screening-runs", response_model=list[ScreeningRunOut])
def list_screening_runs(profile_id: str, db: Session = Depends(get_db)):
    """
    Batch screening runs for this profile, newest first -- powers the
    "show only this screening" filter on the Results screens. Each run is
    one point-in-time criteria state, so filtering by run answers "which
    candidates were judged under those criteria".

    Only runs that still HAVE candidates (as their latest screening) are
    returned -- a run whose candidates were all re-screened later, deleted,
    or that predates run-tagging would filter to an empty table, so
    offering it is only confusing. current_candidates carries the live
    count for each run.
    """
    counts = dict(
        db.query(Candidate.last_screening_run_id, func.count(Candidate.id))
        .filter(
            Candidate.job_profile_id == profile_id,
            Candidate.last_screening_run_id.isnot(None),
        )
        .group_by(Candidate.last_screening_run_id)
        .all()
    )
    runs = (
        db.query(ScreeningRun)
        .filter(ScreeningRun.job_profile_id == profile_id)
        .order_by(ScreeningRun.started_at.desc())
        .all()
    )
    # A stopped run that can still be continued is kept even with no
    # candidates yet, so its "Continue" stays reachable.
    out = [_run_out(db, r, current_candidates=counts.get(r.id, 0)) for r in runs]
    return [r for r in out if r.current_candidates or r.remaining_candidates]


@batch_router.get("/screening-runs/{run_id}", response_model=ScreeningRunOut)
def get_screening_run_status(profile_id: str, run_id: str, db: Session = Depends(get_db)):
    """Poll this for live progress ('X of Y candidates processed')."""
    run = (
        db.query(ScreeningRun)
        .filter(ScreeningRun.id == run_id, ScreeningRun.job_profile_id == profile_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found")
    return _run_out(db, run)


@batch_router.post("/screening-runs/{run_id}/stop", response_model=ScreeningRunOut)
def stop_screening_run(profile_id: str, run_id: str, db: Session = Depends(get_db)):
    """
    Stops a running batch. Candidates not yet picked up are skipped (they
    keep whatever result they had before); candidates already being
    evaluated finish first, so the run sits at "stopping" until they do
    and then becomes "stopped".
    """
    run = (
        db.query(ScreeningRun)
        .filter(ScreeningRun.id == run_id, ScreeningRun.job_profile_id == profile_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found")
    if run.status == "running":
        run.status = "stopping"
        db.commit()
        db.refresh(run)
    return _run_out(db, run)


@batch_router.post("/screening-runs/{run_id}/continue", response_model=ScreeningRunOut)
def continue_screening_run(
    profile_id: str, run_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Continues a stopped (or crashed) run IN PLACE: only the candidates it
    never reached are screened, and they join the same run -- so one
    re-screen stays one session in the history, with its counts picking
    up where they left off.
    """
    run = (
        db.query(ScreeningRun)
        .filter(ScreeningRun.id == run_id, ScreeningRun.job_profile_id == profile_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"Screening run '{run_id}' not found")
    remaining = _remaining_candidate_ids(db, run)
    if not remaining:
        raise HTTPException(status_code=409, detail="This screening has nothing left to continue.")

    run.status = "running"
    run.completed_at = None
    # Candidates deleted since the stop drop out of the total.
    run.total_candidates = run.processed_count + len(remaining)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(_run_batch_screening, run.id, profile_id, remaining)
    return _run_out(db, run)
