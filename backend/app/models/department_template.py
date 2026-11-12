"""
DepartmentTemplate: how ONE department's candidate Excel is laid out.

Every department collects applicants in its own sheet (different column
names, sometimes a title row above the headers, sometimes per-document URL
columns, sometimes none). Instead of hard-coding those names in the
ingestion code, a template maps them onto the small set of fields the
screening engine understands. No AI is involved -- an admin picks the
mapping once from the sheet's own headers.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Fields the engine understands, mapped from a department's own column names.
CANONICAL_FIELDS = ("external_id", "name", "email", "phone", "dob", "gender", "category")

# documents_primary: certificates/letters are the proof; declared data and
#                    CV are only claims (IHMCL).
# declared_primary:  the department collects no proof documents -- the
#                    application row is the main evidence, the resume
#                    corroborates it, and a missing proof document is not a
#                    reason to send someone to manual review (DIC).
EVIDENCE_MODES = ("documents_primary", "declared_primary")


def gen_uuid() -> str:
    return str(uuid.uuid4())


class DepartmentTemplate(Base):
    __tablename__ = "department_templates"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # {"external_id": "S. No", "name": "Candidate Name", ...}; a field may
    # be missing/None when the sheet has no such column.
    field_map: Mapped[dict] = mapped_column(JSON, default=dict)

    # 0-based row holding the column headers. NULL = auto-detect (some
    # exports put a title row above the headers).
    header_row: Mapped[int] = mapped_column(Integer, nullable=True)

    # {document_type: Excel column holding that document's URL}. Empty for
    # departments whose ZIP folders simply hold every document unlabeled.
    document_columns: Mapped[dict] = mapped_column(JSON, default=dict)

    # Case-insensitive filename fragments that identify the resume/CV file
    # inside a candidate's folder (used when document_columns is empty).
    resume_filename_patterns: Mapped[list] = mapped_column(JSON, default=list)

    evidence_mode: Mapped[str] = mapped_column(String(30), default="documents_primary")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
