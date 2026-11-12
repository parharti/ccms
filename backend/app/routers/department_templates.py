"""
Department templates: how each department's candidate sheet is laid out.

Flow: upload a blank/sample sheet to /inspect -> get its column headers ->
admin picks which column is the id / name / category / ... -> save. No AI:
the admin knows the department's sheet. Candidate uploads then pick a
template by id (see routers/candidates.py).
"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.department_template import (
    CANONICAL_FIELDS,
    EVIDENCE_MODES,
    DepartmentTemplate,
)
from app.services.auth_service import get_current_hr_user
from app.services.candidate_ingestion import ALL_DOCUMENT_COLUMNS
from app.services.column_mapping import list_sheet_headers

router = APIRouter(
    prefix="/department-templates",
    tags=["department-templates"],
    dependencies=[Depends(get_current_hr_user)],
)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    field_map: dict[str, Optional[str]]
    header_row: Optional[int] = None
    document_columns: dict[str, str] = {}
    resume_filename_patterns: list[str] = []
    evidence_mode: str = "documents_primary"


class TemplateOut(TemplateIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


def _validate(body: TemplateIn) -> None:
    if not body.field_map.get("external_id"):
        raise HTTPException(status_code=422, detail="A column must be mapped to the candidate ID.")
    unknown = set(body.field_map) - set(CANONICAL_FIELDS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown fields: {', '.join(sorted(unknown))}")
    if body.evidence_mode not in EVIDENCE_MODES:
        raise HTTPException(status_code=422, detail=f"evidence_mode must be one of {EVIDENCE_MODES}")
    if not body.document_columns and not body.resume_filename_patterns:
        raise HTTPException(
            status_code=422,
            detail="Without per-document columns, give at least one resume filename pattern (e.g. 'resume').",
        )


@router.post("/inspect")
def inspect_sheet(file: UploadFile = File(...), header_row: Optional[int] = Form(None)):
    """Column headers (+ sample rows) of an uploaded blank/sample sheet."""
    suffix = os.path.splitext(file.filename or "")[1] or ".xls"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = tmp.name
    try:
        return list_sheet_headers(path, header_row)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read the sheet: {e}")
    finally:
        os.unlink(path)


@router.get("", response_model=list[TemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return db.query(DepartmentTemplate).order_by(DepartmentTemplate.name).all()


@router.post("", response_model=TemplateOut)
def create_template(body: TemplateIn, db: Session = Depends(get_db)):
    _validate(body)
    if db.query(DepartmentTemplate).filter(DepartmentTemplate.name == body.name).first():
        raise HTTPException(status_code=409, detail="A template with this name already exists.")
    template = DepartmentTemplate(**body.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.put("/{template_id}", response_model=TemplateOut)
def update_template(template_id: str, body: TemplateIn, db: Session = Depends(get_db)):
    _validate(body)
    template = db.query(DepartmentTemplate).filter(DepartmentTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    clash = (
        db.query(DepartmentTemplate)
        .filter(DepartmentTemplate.name == body.name, DepartmentTemplate.id != template_id)
        .first()
    )
    if clash:
        raise HTTPException(status_code=409, detail="A template with this name already exists.")
    for key, value in body.model_dump().items():
        setattr(template, key, value)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    template = db.query(DepartmentTemplate).filter(DepartmentTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"deleted": template_id}


def seed_default_templates(db: Session) -> None:
    """The two layouts we already know. Created once, by name; never
    overwritten, so admin edits survive restarts."""
    defaults = [
        dict(
            name="IHMCL",
            description="IHMCL export: Id. column, per-document URL columns, documents are the proof.",
            field_map={
                "external_id": "Id.", "name": "Name", "email": "Email", "phone": "Phone",
                "dob": "DOB", "gender": "Gender", "category": "Category",
            },
            header_row=0,
            document_columns=dict(ALL_DOCUMENT_COLUMNS),
            resume_filename_patterns=[],
            evidence_mode="documents_primary",
        ),
        dict(
            name="DIC",
            description="DIC sheet: S. No as id, no document columns; resume is inside the candidate's folder.",
            field_map={
                "external_id": "S. No", "name": "Candidate Name", "email": "Email",
                "phone": "Phone", "dob": "DOB", "gender": None, "category": "Category",
            },
            header_row=None,
            document_columns={},
            resume_filename_patterns=["resume", "cv"],
            evidence_mode="declared_primary",
        ),
    ]
    for spec in defaults:
        if not db.query(DepartmentTemplate).filter(DepartmentTemplate.name == spec["name"]).first():
            db.add(DepartmentTemplate(**spec))
    db.commit()
