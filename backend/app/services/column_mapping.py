"""
Reads a department's candidate sheet and normalizes it through a
DepartmentTemplate (see models/department_template.py).

The rest of the pipeline (ingestion, evaluation) works against a fixed set
of canonical column names ("Id.", "Name", "Email", "Phone", "DOB", "Gender",
"Category"). apply_template() adds those columns, copied from whichever
columns the department actually uses, and leaves every original column in
place -- so unmapped columns still reach screening as declared data.
"""

from datetime import date, timedelta

import pandas as pd

# canonical field -> the column name the downstream code reads
CANONICAL_COLUMN_NAMES = {
    "external_id": "Id.",
    "name": "Name",
    "email": "Email",
    "phone": "Phone",
    "dob": "DOB",
    "gender": "Gender",
    "category": "Category",
}

# Only the first rows are inspected when looking for the header row.
_HEADER_SCAN_ROWS = 10


def _read_raw_sheet(file_path: str) -> pd.DataFrame:
    """Whole sheet with no header interpretation. Real Excel (.xls/.xlsx)
    first; some exports are really tab-separated text despite the .xls
    extension, so fall back to that."""
    try:
        return pd.read_excel(file_path, header=None)
    except Exception:
        return pd.read_csv(file_path, sep="\t", header=None, dtype=str)


def detect_header_row(raw: pd.DataFrame) -> int:
    """0-based index of the header row: the first of the leading rows that
    is about as full as the fullest one (skips a one-cell title row)."""
    head = raw.head(_HEADER_SCAN_ROWS)
    counts = [int(head.iloc[i].notna().sum()) for i in range(len(head))]
    if not counts:
        return 0
    widest = max(counts)
    for i, count in enumerate(counts):
        if count >= max(1, widest * 0.5):
            return i
    return 0


def _clean_header(value) -> str:
    return str(value).strip() if pd.notna(value) else ""


def load_sheet(file_path: str, header_row: int | None = None) -> pd.DataFrame:
    """The sheet as a DataFrame whose columns are the (whitespace-stripped)
    headers. `header_row` None = auto-detect."""
    raw = _read_raw_sheet(file_path)
    if raw.empty:
        return raw
    row = detect_header_row(raw) if header_row is None else header_row
    headers = [_clean_header(v) for v in raw.iloc[row].tolist()]
    body = raw.iloc[row + 1:].reset_index(drop=True)
    body.columns = headers
    # Drop unnamed spacer columns and fully empty rows.
    body = body.loc[:, [c for c in body.columns if c]]
    return body.dropna(how="all").reset_index(drop=True)


def list_sheet_headers(file_path: str, header_row: int | None = None) -> dict:
    """What the template editor shows: the detected header row, its column
    names, and a few sample rows to help the admin pick the right mapping."""
    df = load_sheet(file_path, header_row)
    raw = _read_raw_sheet(file_path)
    detected = detect_header_row(raw) if header_row is None and not raw.empty else (header_row or 0)
    sample = df.head(3).astype(object).where(df.head(3).notna(), None)
    return {
        "header_row": detected,
        "headers": [str(c) for c in df.columns],
        "sample_rows": [
            {str(k): (None if v is None else str(v)) for k, v in row.items()}
            for row in sample.to_dict(orient="records")
        ],
    }


def _clean_scalar_id(value) -> str | None:
    """'1.0' / 1.0 -> '1'; other values just stripped. NaN -> None."""
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text or None


def _excel_serial_to_date_str(value) -> str | None:
    """Excel stores dates as day counts (36491 = 1999-11-27). Anything
    that isn't a plausible serial is returned as plain text."""
    if pd.isna(value):
        return None
    if hasattr(value, "strftime"):  # pandas already parsed a date-formatted cell
        return value.strftime("%d-%m-%Y")
    try:
        serial = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None
    if 1 <= serial <= 80000:
        d = date(1899, 12, 30) + timedelta(days=int(serial))
        return d.strftime("%d-%m-%Y")
    return str(value).strip()


def apply_template(df: pd.DataFrame, field_map: dict) -> pd.DataFrame:
    """Adds the canonical columns, copied from the mapped source columns.
    Raises ValueError listing any mapped column the sheet doesn't have, or
    when no id column is mapped (candidates can't be matched without it)."""
    if not field_map.get("external_id"):
        raise ValueError("The template has no column mapped to the candidate ID.")

    missing = [
        col for col in field_map.values() if col and col not in df.columns
    ]
    if missing:
        raise ValueError(
            "These mapped columns were not found in the uploaded sheet: "
            + ", ".join(sorted(set(missing)))
            + ". Check that the right department template is selected."
        )

    out = df.copy()
    for field, canonical in CANONICAL_COLUMN_NAMES.items():
        source = field_map.get(field)
        if not source:
            out[canonical] = None
            continue
        series = df[source]
        if field == "external_id":
            out[canonical] = series.map(_clean_scalar_id)
        elif field == "phone":
            out[canonical] = series.map(_clean_scalar_id)
        elif field == "dob":
            out[canonical] = series.map(_excel_serial_to_date_str)
        else:
            out[canonical] = series

    # A row with no id can't be matched to a folder -- drop it.
    out = out[out["Id."].notna()].reset_index(drop=True)
    return out
