"""
Downloads a candidate's resume from the link in the department's sheet.

Only PDFs are accepted (the rest of the pipeline reads PDF text). Anything
else -- an HTML login/viewer page, a Word file, a dead link -- is reported as
a short, human-readable failure reason, never raised past the caller.
"""

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RESUME_BYTES = 15 * 1024 * 1024
TIMEOUT_SECONDS = 30
ATTEMPTS = 3

_USER_AGENT = "Mozilla/5.0 (compatible; ResumeScreeningPortal/1.0)"


class ResumeFetchError(Exception):
    """The resume could not be downloaded; the message is shown to HR."""


def normalize_share_link(url: str) -> str:
    """Rewrites common 'viewer' share links into direct-download links."""
    url = url.strip()
    drive = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=\w+&)?id=)([\w-]+)", url)
    if drive:
        return f"https://drive.google.com/uc?export=download&id={drive.group(1)}"
    if "dropbox.com" in url:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        query["dl"] = "1"
        return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    return url


def _download_once(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_RESUME_BYTES:
            raise ResumeFetchError("The resume file is larger than 15 MB.")
        data = response.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise ResumeFetchError("The resume file is larger than 15 MB.")
    return data


def fetch_resume_pdf(url: str, destination_path: str) -> None:
    """Downloads `url` to `destination_path` (a .pdf). Raises ResumeFetchError
    with a readable reason on any failure. Network errors and 429/5xx are
    retried; a definitive answer (404, login page, not a PDF) is not."""
    link = normalize_share_link(url)
    if not re.match(r"^https?://", link, re.IGNORECASE):
        raise ResumeFetchError("The resume link is not a web address (http/https).")

    last_error = "unknown error"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            data = _download_once(link)
        except ResumeFetchError:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise ResumeFetchError(f"The resume link needs a login or is not public (HTTP {e.code}).")
            if e.code == 404:
                raise ResumeFetchError("The resume link is dead (HTTP 404).")
            last_error = f"HTTP {e.code}"
            if e.code != 429 and e.code < 500:
                raise ResumeFetchError(f"The resume link returned {last_error}.")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = str(getattr(e, "reason", e))
        else:
            if data[:5] != b"%PDF-":
                kind = "a web page (probably a login or viewer page)" if data.lstrip()[:1] == b"<" else "not a PDF"
                raise ResumeFetchError(f"The resume link did not return a PDF -- it returned {kind}.")
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            with open(destination_path, "wb") as f:
                f.write(data)
            return

        if attempt < ATTEMPTS:
            time.sleep(2 * attempt)

    raise ResumeFetchError(f"Could not download the resume after {ATTEMPTS} attempts ({last_error}).")
