"""
FastAPI app entry point.

To run:
    uvicorn app.main:app --reload

Then interactive API docs (Swagger UI) will be available at
http://localhost:8000/docs, where you can test the /jd/upload endpoint
directly, without building a frontend.
"""

import os

# Load environment variables from a .env file, if one exists, BEFORE any
# other app module is imported. This must happen first -- modules like
# app.db.session and app.services.gemini_service read DATABASE_URL /
# GEMINI_API_KEY / SECRET_KEY with os.getenv() at import time, so if this
# loads after those imports, it would be too late to have any effect.
#
# This is what lets each teammate set up their own DATABASE_URL/API key
# ONCE in a .env file, instead of needing to run 'set VAR=value' in every
# new terminal session (easy to forget, and the #1 cause of "works on my
# machine, not on my teammate's machine" for this project).
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine
# Models need to be imported here so that Base.metadata "sees" them when
# create_all() is called -- otherwise their tables won't be created.
from app.models import hr_user, job_profile, candidate, criterion_evaluation, screening_run, department_template  # noqa: F401
from app.routers import auth, jd_upload, job_profiles, candidates, screening, results, review, dashboard, department_templates, resumes

app = FastAPI(title="RecruitAI HR Screening System")

# The frontend runs on a different origin (e.g. http://localhost:5173 for
# Vite's dev server) than the backend (http://localhost:8000), so the
# browser needs explicit CORS permission -- and because auth uses a
# cookie (not a bearer token), allow_credentials must be True and the
# origin list can't use a wildcard "*" (browsers reject credentialed
# requests with a wildcard origin).
FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple create_all() for now -- creates tables if they don't already
# exist. In production, this should be replaced with Alembic migrations
# instead (to properly track/version schema changes).
Base.metadata.create_all(bind=engine)

# create_all() never ADDS columns to tables that already exist, and deploys
# are automatic on push -- so until Alembic is introduced, additive nullable
# columns are applied here (idempotent thanks to IF NOT EXISTS) instead of
# requiring a manual ALTER on the production database.
from sqlalchemy import text  # noqa: E402

with engine.begin() as conn:
    conn.execute(text(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS last_screening_run_id UUID"
    ))
    conn.execute(text(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS cv_certifications JSON"
    ))
    conn.execute(text(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS has_cyber_security_certification BOOLEAN"
    ))
    conn.execute(text(
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_consistency JSON"
    ))
    conn.execute(text(
        "ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS department_template_id UUID"
    ))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS roster_position INTEGER"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS review_tag VARCHAR(30)"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS review_note VARCHAR(500)"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS suitability_score INTEGER"))
    for _col, _ddl in (
        ("experience_tolerance_years", "DOUBLE PRECISION DEFAULT 2.0"),
        ("exception_skills_threshold", "INTEGER DEFAULT 80"),
        ("weight_skills", "INTEGER DEFAULT 50"),
        ("weight_experience", "INTEGER DEFAULT 30"),
        ("weight_desirable", "INTEGER DEFAULT 20"),
        ("close_miss_skills_min", "INTEGER"),
        ("close_miss_experience_min", "INTEGER"),
        ("close_miss_desirable_min", "INTEGER"),
        ("rank_by_suitability", "BOOLEAN DEFAULT TRUE"),
    ):
        conn.execute(text(f"ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS {_col} {_ddl}"))
    conn.execute(text("ALTER TABLE criteria ADD COLUMN IF NOT EXISTS skill_items JSON"))
    conn.execute(text("ALTER TABLE criteria ADD COLUMN IF NOT EXISTS related_mark DOUBLE PRECISION"))
    conn.execute(text("ALTER TABLE criterion_evaluations ADD COLUMN IF NOT EXISTS skill_marks JSON"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS gov_experience JSON"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS gov_relevant_experience BOOLEAN"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_link TEXT"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_fetch_status VARCHAR(20)"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS resume_fetch_error VARCHAR(500)"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS criteria_fingerprint VARCHAR(64)"))
    conn.execute(text("ALTER TABLE screening_runs ADD COLUMN IF NOT EXISTS candidate_ids JSON"))
    conn.execute(text("ALTER TABLE job_profiles ADD COLUMN IF NOT EXISTS competencies JSON"))
    conn.execute(text("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS competency_scores JSON"))

from app.db.session import SessionLocal  # noqa: E402

with SessionLocal() as _seed_db:
    department_templates.seed_default_templates(_seed_db)

# Results screened before criteria fingerprints existed get one, so the
# "outdated results" check works for them too (no-op once backfilled).
from app.services.candidate_evaluation import backfill_criteria_fingerprints  # noqa: E402

with SessionLocal() as _backfill_db:
    backfill_criteria_fingerprints(_backfill_db)

# Screening runs execute on in-process background threads. If the process
# dies mid-run (deploy rebuild, VM stop, crash), the run row stays
# "running" forever -- which permanently blocks candidate deletion (the
# 409 in-progress guard) and shows a phantom live screening. A freshly
# started process by definition has no live screenings, so any run still
# marked "running" now is dead: mark it failed so the app stays usable.
with engine.begin() as conn:
    conn.execute(text(
        "UPDATE screening_runs SET status = 'failed', "
        "completed_at = COALESCE(completed_at, NOW()) WHERE status IN ('running', 'stopping')"
    ))

# Resume fetches also run on in-process threads: a candidate left "fetching"
# by a dead process goes back to "pending" so it can be fetched again.
with engine.begin() as conn:
    conn.execute(text(
        "UPDATE candidates SET resume_fetch_status = 'pending' "
        "WHERE resume_fetch_status = 'fetching'"
    ))

app.include_router(auth.router)
app.include_router(jd_upload.router)
app.include_router(job_profiles.router)
app.include_router(candidates.router)
app.include_router(resumes.router)
app.include_router(screening.single_router)
app.include_router(screening.batch_router)
app.include_router(results.router)
app.include_router(review.router)
app.include_router(dashboard.router)
app.include_router(department_templates.router)


@app.get("/")
def root():
    return {"status": "RecruitAI HR Screening System API is running"}
