"""
Candidate ingestion service.

Parses the candidate master data file and a master ZIP containing one
plain FOLDER per candidate, matches each candidate to their Excel row,
extracts their documents to persistent storage, and tags each document
using the Excel's own document URL columns as the source of truth --
rather than guessing from filenames.

Two folder naming conventions are supported (a single upload may mix
both -- each folder is tried against the roster under both):
  new: '<application-id>_<candidate name>', e.g.
       'IHMCL-APP-7W-2713_Dasari_Lokesh_Kumar' (Id. = 'IHMCL-APP-7W-2713')
  old: the Excel "Id." with slashes flattened to underscores, e.g.
       'IHM_JA_1900_10001' (Id. = 'IHM/JA/1900/10001')

Older exports where the master ZIP holds one nested ZIP per candidate
(instead of a folder) are still accepted -- the format is auto-detected
from the ZIP's contents.

This logic was first validated as a standalone script (test_candidate_ingest.py)
against real IHMCL export data before being wired into this service.
"""

import os
import io
import json
import re
import shutil
import uuid
import zipfile

import pandas as pd

from app.services.age_relaxation import normalize_candidate_category

# Maps a clean internal "document_type" key -> the Excel column name that
# holds the URL to that document.
#
# "resume_cv" is stored but is NOT proof: a CV is authored by the
# candidate, so evaluation feeds it to Gemini as a separate CLAIMS
# section (a fallback for facts the Excel row doesn't mention), never as
# document evidence -- see evaluate_candidate, which splits it out of
# the document context.
FIXED_DOCUMENT_COLUMNS = {
    "photograph": "Photograph",
    "signature": "Signature",
    "10th_marksheet": "10th Mark File",
    "graduation_certificate": "Graduation File",
    "salary_slip": "Salary Slip File",
    "resume_cv": "User CV File",
    "pwbd_certificate": "PwBD File",
    "category_certificate": "Category Certi File",
}

# Work File1 .. Work File8 -> experience_proof_1 .. experience_proof_8
WORK_FILE_COLUMNS = {f"experience_proof_{i}": f"Work File{i}" for i in range(1, 9)}

ALL_DOCUMENT_COLUMNS = {**FIXED_DOCUMENT_COLUMNS, **WORK_FILE_COLUMNS}


def load_candidate_master_data(file_path: str) -> pd.DataFrame:
    """
    Loads the candidate master data file.

    Note: despite typically having a .xls extension, IHMCL's export is
    actually a tab-separated plain text file, not a real Excel binary.
    We try the real Excel reader first (in case a future export IS a
    genuine .xls/.xlsx), and fall back to tab-separated parsing.
    """
    try:
        return pd.read_excel(file_path)
    except Exception:
        return pd.read_csv(file_path, sep="\t")


def candidate_ids_from_name(name: str) -> list[str]:
    """
    Possible Excel "Id." values for a candidate folder (or nested-ZIP)
    name, covering BOTH naming conventions -- callers try each against
    the roster and the first match wins:

      new: '<application-id>_<candidate name>'
           'IHMCL-APP-7W-2713_Dasari_Lokesh_Kumar' -> 'IHMCL-APP-7W-2713'
      old: the Excel id with its slashes flattened to underscores
           'IHM_JA_1900_10001[_downloaded_files]'  -> 'IHM/JA/1900/10001'
    """
    base = name.replace("_downloaded_files", "")
    if base.lower().endswith(".zip"):
        base = base[:-4]
    new_style = base.split("_", 1)[0]
    old_style = base.replace("_", "/", 3)
    return [new_style, old_style]


def _best_guess_id(name: str) -> str:
    """When no roster row matches, pick the more plausible id for the
    'excel_row_not_found' record: hyphens in the first segment mean the
    new application-id convention; otherwise assume the old one."""
    new_style, old_style = candidate_ids_from_name(name)
    return new_style if ("-" in new_style or new_style.isdigit()) else old_style


def _find_roster_row(df: pd.DataFrame, name: str):
    """(candidate_id, row) for the first naming convention that matches a
    roster row, or (best-guess id, None) when none does."""
    for candidate_id in candidate_ids_from_name(name):
        rows = df[df["Id."].astype(str) == candidate_id]
        if not rows.empty:
            return candidate_id, rows.iloc[0]
    return _best_guess_id(name), None


def extract_filename_from_url(url) -> str | None:
    """Gets just the filename from a full document URL. Returns None for
    empty/N/A values."""
    if pd.isna(url):
        return None
    url_str = str(url).strip()
    if url_str in ("", "N/a", "n/a", "NA", "nan"):
        return None
    return url_str.rstrip("/").split("/")[-1]


def match_candidate_documents(
    candidate_row: pd.Series,
    candidate_files_dir: str,
    document_columns: dict | None = None,
    resume_patterns: list | None = None,
) -> dict:
    """
    For a single candidate, matches each expected document type to an
    actual file found on disk (inside their extracted folder).

    document_columns None -> the original IHMCL layout (ALL_DOCUMENT_COLUMNS).
    document_columns {}   -> the department's sheet has no per-document URL
    columns, so every file in the folder is a document: the one whose name
    contains a resume pattern is the resume_cv, the rest become
    document_1, document_2, ...
    """
    files_on_disk = {}
    for fname in os.listdir(candidate_files_dir):
        full_path = os.path.join(candidate_files_dir, fname)
        if os.path.isfile(full_path):
            files_on_disk[fname.lower()] = full_path

    if document_columns is not None and not document_columns:
        return _match_unlabeled_documents(files_on_disk, resume_patterns or [])

    columns = ALL_DOCUMENT_COLUMNS if document_columns is None else document_columns

    matched = {}
    expected_but_missing = []

    for doc_type, column_name in columns.items():
        if column_name not in candidate_row:
            continue
        expected_filename = extract_filename_from_url(candidate_row[column_name])
        if expected_filename is None:
            continue  # Excel says this document doesn't apply to this candidate

        match = files_on_disk.get(expected_filename.lower())
        if match:
            matched[doc_type] = match
            files_on_disk.pop(expected_filename.lower(), None)
        else:
            expected_but_missing.append(doc_type)

    return {"matched": matched, "expected_but_missing": expected_but_missing}


def _match_unlabeled_documents(files_on_disk: dict, resume_patterns: list) -> dict:
    """Folder-only matching: no Excel column says which file is which, so
    the resume is recognised by filename and the rest are numbered. A
    folder with files but no recognisable resume reports the resume as
    expected-but-missing (the resume is mandatory for these departments)."""
    patterns = [p.lower() for p in resume_patterns if p]
    matched = {}
    resume_name = next(
        (n for n in sorted(files_on_disk) if any(p in n for p in patterns)), None
    )
    if resume_name:
        matched["resume_cv"] = files_on_disk.pop(resume_name)

    # Photos/signatures carry no screening text; keep them out of the way
    # of the numbering but still stored (they are skipped at evaluation).
    for i, name in enumerate(sorted(files_on_disk), start=1):
        matched[f"document_{i}"] = files_on_disk[name]

    missing = [] if resume_name or not patterns else ["resume_cv"]
    return {"matched": matched, "expected_but_missing": missing}


def _row_to_json_safe_dict(row: pd.Series) -> dict:
    """
    Converts a pandas row into a plain, JSON-serializable dict.

    Using row.to_json() and re-parsing is a simple, reliable way to get
    rid of pandas/numpy-specific types (Timestamps, int64, NaN) that the
    database's JSON column wouldn't otherwise accept directly.
    """
    return json.loads(row.to_json())


def _build_candidate_result(
    candidate_row: pd.Series, candidate_id: str, candidate_dir: str, config: dict | None = None
) -> dict:
    """Matches a candidate's extracted documents and assembles the result
    dict the upload router turns into Candidate + CandidateDocument rows."""
    config = config or {}
    doc_result = match_candidate_documents(
        candidate_row,
        candidate_dir,
        document_columns=config.get("document_columns"),
        resume_patterns=config.get("resume_patterns"),
    )

    if doc_result["matched"] and not doc_result["expected_but_missing"]:
        ingestion_status = "documents_complete"
    elif doc_result["matched"]:
        ingestion_status = "documents_incomplete"
    else:
        ingestion_status = "no_documents_found"

    raw_category = candidate_row.get("Category")
    phone = candidate_row.get("Phone")
    dob = candidate_row.get("DOB")

    return {
        "external_id": candidate_id,
        "name": candidate_row.get("Name"),
        "email": candidate_row.get("Email"),
        "phone": str(phone) if pd.notna(phone) else None,
        "dob": str(dob) if pd.notna(dob) else None,
        "gender": candidate_row.get("Gender"),
        "raw_category": raw_category if pd.notna(raw_category) else None,
        "normalized_category": normalize_candidate_category(raw_category),
        "raw_excel_data": _row_to_json_safe_dict(candidate_row),
        "ingestion_status": ingestion_status,
        "matched_documents": doc_result["matched"],  # {doc_type: local_file_path}
        "expected_but_missing": doc_result["expected_but_missing"],
    }


def process_master_zip(
    df: pd.DataFrame, master_zip_path: str, storage_dir: str, config: dict | None = None
) -> list[dict]:
    """
    Walks through every candidate inside the master ZIP -- one plain
    folder per candidate (current format), or one nested ZIP per
    candidate (older exports; auto-detected) -- matches each to an Excel
    row, and extracts + matches their documents to persistent storage.

    Returns a list of per-candidate result dicts, ready to be turned into
    Candidate + CandidateDocument database rows by the calling router.
    """
    os.makedirs(storage_dir, exist_ok=True)

    with zipfile.ZipFile(master_zip_path) as master_zf:
        # Legacy format: nested per-candidate ZIPs sit at the ROOT of the
        # master ZIP. A .zip file buried deeper is just a stray file in a
        # folder-format upload, not a format signal.
        nested_zip_names = [
            n for n in master_zf.namelist()
            if n.lower().endswith(".zip") and "/" not in n.replace("\\", "/")
        ]
        if nested_zip_names:
            return _process_nested_zips(df, master_zf, nested_zip_names, storage_dir, config)
        return _process_candidate_folders(df, master_zf, storage_dir, config)


def _group_files_by_candidate_folder(df: pd.DataFrame, names: list[str]) -> dict[str, list[str]]:
    """
    {'IHMCL-APP-7W-2713_Dasari_Lokesh_Kumar': [<original zip entries>], ...}

    Candidate folders can sit at ANY depth inside the ZIP -- real exports
    arrive wrapped in several layers (e.g. public_html/controller/
    temp_xxx/<candidate folders>), and Windows adds a wrapper folder when
    zipping a parent directory. Rather than guessing at wrapper layers,
    find the directory depth where folder names actually match roster
    "Id." values (under either naming convention) and group by that
    segment. Files not under any folder at that depth (server junk like
    public_html/index.php) are ignored.
    """
    roster_ids = {str(v) for v in df["Id."].tolist()}

    entries: list[tuple[list[str], str]] = []  # (dir segments, original entry name)
    for name in names:
        norm = name.replace("\\", "/")
        if norm.endswith("/"):
            continue  # directory entries carry no data
        parts = norm.split("/")
        if len(parts) < 2:
            continue  # loose file at the ZIP root -- not inside any candidate folder
        entries.append((parts[:-1], name))

    # Vote: at which depth do folder names match roster ids? (Each file
    # votes once, for its shallowest matching segment.)
    depth_votes: dict[int, int] = {}
    for dirs, _ in entries:
        for depth, segment in enumerate(dirs):
            if any(pid in roster_ids for pid in candidate_ids_from_name(segment)):
                depth_votes[depth] = depth_votes.get(depth, 0) + 1
                break

    if depth_votes:
        candidate_depth = max(depth_votes, key=lambda d: depth_votes[d])
    else:
        # Nothing matches the roster at all (wrong roster / wrong batch).
        # Best-effort report: treat the first depth where the tree fans out
        # into multiple folders as the candidate level, so the resulting
        # "not found in roster" records carry recognizable folder names.
        folders_at_depth: dict[int, set[str]] = {}
        for dirs, _ in entries:
            for depth, segment in enumerate(dirs):
                folders_at_depth.setdefault(depth, set()).add(segment)
        candidate_depth = next(
            (d for d in sorted(folders_at_depth) if len(folders_at_depth[d]) > 1), 0
        )

    groups: dict[str, list[str]] = {}
    for dirs, name in entries:
        if len(dirs) > candidate_depth:
            groups.setdefault(dirs[candidate_depth], []).append(name)
    return groups


def _process_candidate_folders(
    df: pd.DataFrame, master_zf: zipfile.ZipFile, storage_dir: str, config: dict | None = None
) -> list[dict]:
    """Current format: the master ZIP holds one plain folder per candidate
    (possibly buried under wrapper folders -- see the grouping helper)."""
    results = []
    groups = _group_files_by_candidate_folder(df, master_zf.namelist())

    for folder_name, file_entries in groups.items():
        candidate_id, candidate_row = _find_roster_row(df, folder_name)
        if candidate_row is None:
            # We know a candidate folder exists, but have no Excel data
            # for them at all -- still record this so it's visible
            # during review, rather than silently dropping it.
            results.append({
                "external_id": candidate_id,
                "ingestion_status": "excel_row_not_found",
            })
            continue

        candidate_dir = os.path.join(storage_dir, str(uuid.uuid4()))
        os.makedirs(candidate_dir, exist_ok=True)

        # Flatten into candidate_dir: documents may sit in subfolders, but
        # match_candidate_documents() only looks at direct files (matching
        # is by exact filename from the Excel's URL columns, so the path
        # inside the folder carries no information anyway).
        for entry in file_entries:
            filename = os.path.basename(entry.replace("\\", "/"))
            if not filename:
                continue
            with master_zf.open(entry) as src, open(os.path.join(candidate_dir, filename), "wb") as dst:
                shutil.copyfileobj(src, dst)

        results.append(_build_candidate_result(candidate_row, candidate_id, candidate_dir, config))

    return results


# ---------------------------------------------------------------------------
# Resumes-only upload: no roster at all. Each resume in the ZIP is one
# candidate, and the resume is the whole truth about them.
# ---------------------------------------------------------------------------

# Files whose text screening can read (build_document_context).
RESUME_EXTENSIONS = (".pdf", ".docx")
DEFAULT_RESUME_PATTERNS = ("resume", "cv", "biodata", "bio-data", "curriculum")
_JUNK_NAMES = ("thumbs.db", "desktop.ini")


def _is_junk_entry(parts: list[str]) -> bool:
    """macOS/Windows metadata that zipping a folder drags along."""
    return (
        any(p == "__MACOSX" for p in parts)
        or parts[-1].startswith(".")
        or parts[-1].lower() in _JUNK_NAMES
    )


def guess_name_from_filename(filename: str) -> str | None:
    """'01-aarav-mehta.pdf' -> 'Aarav Mehta', 'Resume_John_Doe (1).pdf' ->
    'John Doe'. Only a placeholder: screening replaces it with the name read
    from the resume itself. None when nothing name-like is left."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    words = [
        w for w in re.split(r"[^A-Za-z]+", stem)
        if w and w.lower() not in DEFAULT_RESUME_PATTERNS + ("updated", "final", "new", "latest", "copy", "of")
    ]
    return " ".join(w.capitalize() for w in words) or None


def _pick_resume(filenames: list[str], patterns: list[str]) -> str | None:
    """The resume among one candidate folder's files: a name containing a
    resume pattern first, else the only readable file, else the first
    readable PDF/DOCX."""
    readable = sorted(f for f in filenames if f.lower().endswith(RESUME_EXTENSIONS))
    named = [f for f in readable if any(p in f.lower() for p in patterns)]
    if named:
        return named[0]
    return readable[0] if readable else None


def process_resume_zip(zip_path: str, storage_dir: str, resume_patterns: list | None = None) -> list[dict]:
    """
    Turns a ZIP of resumes into one candidate per resume. Two layouts, which
    may be mixed:
      - loose files:  every PDF/DOCX is one candidate (id = file name)
      - folders:      every folder is one candidate (id = folder name); the
                      resume is picked by name, other files are kept as
                      supporting documents
    Wrapper folders around everything (Windows adds one when zipping a
    folder) are skipped.

    Returns result dicts shaped like _build_candidate_result's, with no
    roster data (raw_excel_data None) and ingestion_status "resume_only"
    when a readable resume was found, else "no_documents_found".
    """
    patterns = [p.lower() for p in (resume_patterns or DEFAULT_RESUME_PATTERNS) if p]
    os.makedirs(storage_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        entries: list[tuple[list[str], str]] = []
        for name in zf.namelist():
            norm = name.replace("\\", "/")
            if norm.endswith("/"):
                continue
            parts = [p for p in norm.split("/") if p]
            if parts and not _is_junk_entry(parts):
                entries.append((parts, name))

        # Strip wrapper folders shared by every entry.
        while entries and all(len(p) > 1 for p, _ in entries) and len({p[0] for p, _ in entries}) == 1:
            entries = [(p[1:], n) for p, n in entries]

        groups: dict[str, list[tuple[str, str]]] = {}  # key -> [(filename, zip entry)]
        for parts, name in entries:
            if len(parts) == 1:
                if parts[0].lower().endswith(RESUME_EXTENSIONS):
                    groups.setdefault("file:" + parts[0], []).append((parts[0], name))
            else:
                groups.setdefault("dir:" + parts[0], []).append((parts[-1], name))

        results = []
        used_ids: set[str] = set()
        for key, files in groups.items():
            label = key.split(":", 1)[1]
            is_folder = key.startswith("dir:")
            external_id = label if is_folder else os.path.splitext(label)[0]
            base_id, n = external_id[:100], 2
            external_id = base_id
            while external_id in used_ids:
                external_id = f"{base_id[:95]}-{n}"
                n += 1
            used_ids.add(external_id)

            candidate_dir = os.path.join(storage_dir, str(uuid.uuid4()))
            os.makedirs(candidate_dir, exist_ok=True)
            local_paths: dict[str, str] = {}
            for filename, entry in files:
                target = os.path.join(candidate_dir, filename)
                if os.path.exists(target):
                    target = os.path.join(candidate_dir, f"{uuid.uuid4().hex[:6]}_{filename}")
                with zf.open(entry) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                local_paths.setdefault(filename, target)

            resume_name = _pick_resume(list(local_paths), patterns)
            matched: dict[str, str] = {}
            if resume_name:
                matched["resume_cv"] = local_paths.pop(resume_name)
            for i, filename in enumerate(sorted(local_paths), start=1):
                matched[f"document_{i}"] = local_paths[filename]

            results.append({
                "external_id": external_id,
                "name": guess_name_from_filename(label if is_folder else (resume_name or label)),
                "raw_excel_data": None,
                "ingestion_status": "resume_only" if resume_name else "no_documents_found",
                "matched_documents": matched,
            })
        return results


def _process_nested_zips(
    df: pd.DataFrame,
    master_zf: zipfile.ZipFile,
    nested_zip_names: list[str],
    storage_dir: str,
    config: dict | None = None,
) -> list[dict]:
    """Older exports: the master ZIP holds one nested ZIP per candidate."""
    results = []

    for nested_name in nested_zip_names:
        candidate_id, candidate_row = _find_roster_row(df, os.path.basename(nested_name))
        if candidate_row is None:
            results.append({
                "external_id": candidate_id,
                "ingestion_status": "excel_row_not_found",
            })
            continue

        candidate_dir = os.path.join(storage_dir, str(uuid.uuid4()))
        os.makedirs(candidate_dir, exist_ok=True)

        try:
            nested_bytes = master_zf.read(nested_name)
            with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested_zf:
                nested_zf.extractall(candidate_dir)
        except zipfile.BadZipFile:
            results.append({
                "external_id": candidate_id,
                "name": candidate_row.get("Name"),
                "ingestion_status": "corrupt_zip",
            })
            continue

        results.append(_build_candidate_result(candidate_row, candidate_id, candidate_dir, config))

    return results
