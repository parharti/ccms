"""
Roster-only ingestion: turns a department's candidate sheet into candidate
records with NO documents ZIP and no per-department template.

  - The header row is auto-detected (a title row above the headers is fine).
  - Name / email / phone / DOB / category / gender / resume-link columns are
    found from their headers.
  - The sheet has no reliable unique ID (e.g. "S. No" just counts 1..N), so
    the portal assigns each row its own: the lower-cased email when the sheet
    has one, otherwise "row-<sheet row number>". Re-uploading the same sheet
    therefore replaces the same candidates instead of duplicating them.
  - The resume link is the cell's real hyperlink target when it has one
    (.xlsx / .xls), otherwise the cell text when that is itself a URL.
"""

import re

import pandas as pd

from app.services.age_relaxation import normalize_candidate_category
from app.services.column_mapping import (
    _clean_header,
    _clean_scalar_id,
    _excel_serial_to_date_str,
    _read_raw_sheet,
    detect_header_row,
)

# Header fragments that disqualify a column from a role (e.g. "Father Name"
# is not the candidate's name, "Ref1 Email" is not the candidate's email).
_NOT_THE_CANDIDATE = ("father", "mother", "spouse", "institute", "org", "ref", "guardian")


def _find_column(headers: list[str], include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> int | None:
    """Index of the first header containing any `include` fragment and none
    of the `exclude` fragments (case-insensitive); an exact match on the
    first fragment wins over a partial one."""
    lowered = [h.lower() for h in headers]
    for i, h in enumerate(lowered):
        if h == include[0]:
            return i
    for i, h in enumerate(lowered):
        if any(f in h for f in include) and not any(x in h for x in exclude):
            return i
    return None


def detect_columns(headers: list[str]) -> dict[str, int | None]:
    """{role: column index or None} for the roles the engine understands."""
    return {
        "name": _find_column(headers, ("candidate name", "name"), _NOT_THE_CANDIDATE),
        "email": _find_column(headers, ("email", "e-mail"), _NOT_THE_CANDIDATE),
        "phone": _find_column(headers, ("phone", "mobile", "contact"), _NOT_THE_CANDIDATE),
        "dob": _find_column(headers, ("dob", "date of birth", "birth")),
        "category": _find_column(headers, ("category",), ("state",)),
        "gender": _find_column(headers, ("gender", "sex")),
        "resume": _find_column(headers, ("resume", "cv", "curriculum")),
    }


def _read_xls_formula_links(file_path: str) -> dict[tuple[int, int], str]:
    """Links stored as =HYPERLINK("url","text") formulas in the first sheet of
    a legacy .xls. xlrd exposes only the cached text of those cells, so the
    formula records are read directly from the BIFF stream."""
    import re
    import struct
    import sys

    from xlrd.compdoc import CompDoc

    with open(file_path, "rb") as fh:
        raw = fh.read()
    doc = CompDoc(raw, sys.stdout, 0)
    located = doc.locate_named_stream("Workbook") or doc.locate_named_stream("Book")
    if not located:
        return {}
    data = located[0][located[1]:located[1] + located[2]]

    links: dict[tuple[int, int], str] = {}
    pos, sheet = 0, -1
    while pos + 4 <= len(data):
        rec_type, length = struct.unpack_from("<HH", data, pos)
        body = data[pos + 4:pos + 4 + length]
        pos += 4 + length
        if rec_type == 0x0809 and len(body) >= 4 and struct.unpack_from("<H", body, 2)[0] == 0x10:
            sheet += 1  # BOF of a worksheet
            if sheet > 0:
                break  # only the first sheet is ingested
        elif rec_type == 0x0006 and sheet == 0:  # FORMULA
            match = re.search(rb"https?://[!-~]+", body)
            if match:
                row, col = struct.unpack_from("<HH", body, 0)
                links[(row, col)] = match.group().decode("ascii").split('"')[0]
    return links


def _read_hyperlinks(file_path: str) -> dict[tuple[int, int], str]:
    """{(0-based sheet row, 0-based column): link target} for every hyperlink
    cell. Empty for tab-separated/text exports, which carry no hyperlinks."""
    links: dict[tuple[int, int], str] = {}
    lower = file_path.lower()
    try:
        if lower.endswith(".xls"):
            import xlrd

            book = xlrd.open_workbook(file_path, formatting_info=True)
            sheet = book.sheet_by_index(0)
            for (r, c), link in sheet.hyperlink_map.items():
                if link.url_or_path:
                    links[(r, c)] = link.url_or_path
            if not links:
                links = _read_xls_formula_links(file_path)
        elif lower.endswith((".xlsx", ".xlsm")):
            import openpyxl

            book = openpyxl.load_workbook(file_path)
            for row in book.worksheets[0].iter_rows():
                for cell in row:
                    if cell.hyperlink is not None and cell.hyperlink.target:
                        links[(cell.row - 1, cell.column - 1)] = cell.hyperlink.target
    except Exception:
        # A hyperlink-reading problem must not block the roster itself --
        # candidates just get "no_link" and HR can use the ZIP fallback.
        return {}
    return links


def _json_safe(value):
    """A cell as a plain JSON-friendly value (dates as dd-mm-YYYY)."""
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%d-%m-%Y")
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value if isinstance(value, (int, float, bool)) else str(value)


def _is_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def parse_roster(file_path: str) -> list[dict]:
    """
    One dict per candidate row, shaped for the Candidate model:
    external_id, name, email, phone, dob, gender, raw_category,
    normalized_category, raw_excel_data, resume_link.

    Raises ValueError for an empty sheet or one with no recognisable name
    or email column (rows could not be told apart / shown to HR).
    """
    raw = _read_raw_sheet(file_path)
    if raw.empty:
        raise ValueError("The uploaded sheet is empty.")

    header_row = detect_header_row(raw)
    headers = [_clean_header(v) for v in raw.iloc[header_row].tolist()]
    columns = detect_columns(headers)
    if columns["name"] is None and columns["email"] is None:
        raise ValueError(
            "Could not find a candidate name or email column in the sheet. "
            f"Columns found: {', '.join(h for h in headers if h) or '(none)'}."
        )

    hyperlinks = _read_hyperlinks(file_path)
    body = raw.iloc[header_row + 1:].dropna(how="all")

    rows: list[dict] = []
    used_ids: set[str] = set()
    for raw_index, series in body.iterrows():
        values = series.tolist()

        def cell(role: str):
            idx = columns[role]
            return values[idx] if idx is not None else None

        name = cell("name")
        email = cell("email")
        email_text = str(email).strip().lower() if pd.notna(email) and str(email).strip() else None
        name_text = str(name).strip() if pd.notna(name) and str(name).strip() else None
        if not name_text and not email_text:
            continue  # a stray row with nothing identifying it

        external_id = email_text if email_text and email_text not in used_ids else f"row-{raw_index + 1}"
        used_ids.add(external_id)

        resume_link = None
        resume_idx = columns["resume"]
        if resume_idx is not None:
            resume_link = hyperlinks.get((raw_index, resume_idx))
            if not resume_link:
                text = values[resume_idx]
                if pd.notna(text) and _is_url(str(text)):
                    resume_link = str(text).strip()

        raw_category = cell("category")
        dob = cell("dob")
        gender = cell("gender")
        category_text = str(raw_category).strip() if pd.notna(raw_category) and str(raw_category).strip() else None

        data = {}
        for i, header in enumerate(headers):
            if header:
                data[header] = _json_safe(values[i])
        if resume_link and resume_idx is not None:
            data[headers[resume_idx]] = resume_link

        rows.append({
            "external_id": external_id,
            "roster_position": len(rows),
            "name": name_text,
            "email": email_text,
            "phone": _clean_scalar_id(cell("phone")),
            "dob": _excel_serial_to_date_str(dob),
            "gender": str(gender).strip() if pd.notna(gender) and str(gender).strip() else None,
            "raw_category": category_text,
            "normalized_category": normalize_candidate_category(category_text),
            "raw_excel_data": data,
            "resume_link": resume_link,
        })

    if not rows:
        raise ValueError("No candidate rows were found under the header row.")
    return rows
