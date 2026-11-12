"""
Structured JSON extraction from a JD using Gemini.

This is the same logic that was validated in a standalone test script
(test_jd_parser.py) before being turned into a reusable service function
that the FastAPI router calls.
"""

import os
import json
import re
import time
from datetime import date
from typing import Optional

from google import genai
from google.genai import errors as genai_errors

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# One place to switch models for every Gemini call this service makes.
# NOTE: the thinking config is family-specific -- the 2.5 family used
# thinking_budget (0 disables thinking), while the 3.x family replaced it
# with thinking_level ("low"/"high"). Change BOTH together when moving
# between families.
#
GEMINI_MODEL = "gemini-3.5-flash-lite"
# "medium" thinking gives the two-stage verification prompts some reasoning
# room without letting per-candidate latency blow up.
GEMINI_GENERATION_CONFIG = {"thinking_config": {"thinking_level": "medium"}}

# One shared client for the whole process -- constructing a new
# genai.Client per call throws away connection reuse, which matters once
# screening runs make many calls back-to-back (and in parallel).
_client: genai.Client | None = None


def _get_client() -> "genai.Client":
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _sleep_before_retry(attempt: int, exc: Exception | None = None) -> None:
    """Back off before the next attempt. A 429 rate limit says how long to
    wait ("Please retry in 40.2s"); honour that instead of the short default,
    otherwise every retry lands inside the same rate-limit window."""
    delay = 2 * attempt
    if exc is not None and "429" in str(exc):
        match = re.search(r"retry in ([\d.]+)s", str(exc))
        delay = min(float(match.group(1)) + 2, 75) if match else 30
    time.sleep(delay)


def _is_retryable(exc: Exception) -> bool:
    """
    Only transient failures are worth retrying (with sleeps). Auth errors,
    invalid requests, oversized prompts etc. will fail identically every
    attempt -- retrying those just burns 6-30s of sleep per criterion for
    nothing, which is exactly what made broken candidates so slow to fail.
    """
    if isinstance(exc, genai_errors.APIError):
        return exc.code in (408, 429, 500, 502, 503, 504)
    return True  # network hiccups / unknown errors -- retry

PROMPT_TEMPLATE = """
You are extracting structured data from a Job Description (JD) advertisement.

The JD may cover ONE post or MULTIPLE posts (roles) in a single advertisement.
For each distinct post you find, extract its title and eligibility criteria.

Extract ONLY criteria that matter for screening and can be VERIFIED against a
candidate's documents (certificates, marksheets, experience letters, CV):

1. AGE (type "age") -- the post's age limit(s), as stated.
2. EXPERIENCE (type "experience") -- ONLY requirements that state a required
   TOTAL number of years, explicitly as a number (e.g. "Minimum 5 years of
   post-qualification experience in ..."). Screening will add up the
   candidate's individual job periods and compare the sum against this
   number, so the number is the whole point. If the JD splits countable
   experience into multiple distinct numeric requirements (e.g. total years
   AND years in a specific role), keep those as separate experience
   criteria, each with its own explicit number.
   A requirement WITHOUT an explicit number of years ("proven track record
   of X", "hands-on experience with Y", "strong understanding of Z",
   "working knowledge of W") is NOT an experience criterion -- it belongs
   in the single skill criterion below.
3. EDUCATION (type "education") -- qualifications/degrees, as concretely as
   the JD states them (degree name, discipline, minimum marks). This
   includes DESIRABLE/preferred degrees (e.g. "Desirable: Master's degree /
   MBA / PGDM ...") -- keep those as separate education criteria whose
   description STARTS with the word "Desirable" (that word is what marks
   them non-mandatory downstream). Degree requirements NEVER belong in the
   skill criterion.
4. OTHER (type "other") -- ONLY for concrete, document-verifiable
   requirements that don't fit above (e.g. a mandatory certification,
   license, or professional registration).
5. SKILLS & QUALITATIVE EXPERIENCE (type "skill") -- create EXACTLY ONE
   criterion of type "skill" per post (at most one; none if the JD has no
   such requirements). Consolidate into its single description EVERY
   qualitative, non-numeric capability requirement the JD mentions:
   skills, tools, technologies, methodologies, domain familiarity, and
   qualitative experience ("proven track record of...", "hands-on
   experience with...", "strong understanding of...", "working knowledge
   of..."). Do NOT create separate criteria for these -- one consolidated
   list. During screening this criterion produces ONE overall match
   percentage and NEVER makes a candidate eligible or not eligible, so no
   mandatory/quantifiable requirement may be placed inside it -- and no
   degree/qualification requirement either (those are education criteria,
   even the desirable ones).
   Also return that criterion's "skill_items": the individual skills it
   lists, each as a SHORT name (1-4 words), one per array entry, e.g.
   ["SQL", "Python", "Power BI", "Statistical analysis", "Stakeholder
   communication"]. Each item is marked separately during screening, so
   split combined phrases ("Python and R" -> "Python", "R") and keep the
   JD's own wording for each skill.

MANDATORY vs NOT: for every criterion also set "mandatory". true ONLY when
the JD itself presents the requirement as compulsory ("mandatory",
"essential", "must", "required", "minimum", or it sits under an
"Essential / Eligibility" heading). false when the JD marks it as
"desirable", "preferred", "preferably", "an advantage" or lists it
as nice-to-have. When the JD does not say either way, use true for age,
education and numeric experience requirements and false for everything
else. The single skill criterion is always false.

Do NOT create criteria for vague personality statements ("hardworking",
"positive attitude", "team player") -- drop those entirely.

Separately, check if the JD contains an "Age Relaxation" section/table --
this is a general table (usually applies to ALL posts in the JD, not
post-specific) that lists extra years added to the base age limit for
categories like SC, ST, OBC, EWS, PwD, Ex-servicemen, etc. This is
DIFFERENT from the post's base age criterion -- do not put it inside
any post's criteria list.

Return ONLY valid JSON, no markdown formatting, no backticks, no extra text.
Use exactly this shape:

{{
  "post_count": <integer>,
  "confidence": "high" | "medium" | "low",
  "ambiguity_notes": "<string, empty if none>",
  "posts": [
    {{
      "title": "<string>",
      "criteria": [
        {{
          "type": "education" | "experience" | "skill" | "age" | "other",
          "description": "<string, the exact requirement>",
          "mandatory": <true | false, see MANDATORY vs NOT above>,
          "skill_items": <["<short skill name>", ...] for the skill criterion only; omit or null for every other type>
        }}
      ]
    }}
  ],
  "age_relaxation": {{
    "mentioned_in_jd": <true | false>,
    "rules": [
      {{
        "category": "<string, e.g. SC, ST, OBC, EWS, PwD_General, PwD_SC_ST, PwD_OBC, Ex-Serviceman, J&K_Domicile, etc.>",
        "relaxation": "<string, e.g. '5 years', '3 years', 'service period + 3 years' -- keep it exactly as worded in the JD>"
      }}
    ]
  }}
}}

Rules:
- If you are unsure whether the JD has 1 post or more than 1, set confidence
  to "low" or "medium" and explain briefly in ambiguity_notes.
- Do not invent criteria that aren't stated or clearly implied in the text.
- If a post's criteria section is unclear/missing, still include the post
  with an empty criteria list, and mention it in ambiguity_notes.
- If the JD does NOT contain any age relaxation section/table, set
  "mentioned_in_jd" to false and "rules" to an empty list. Do not invent
  relaxation rules from general knowledge of government norms -- only
  extract what is explicitly written in this specific JD.

JD TEXT:
---
{jd_text}
---
"""


CRITERION_EVALUATION_PROMPT_TEMPLATE = """
You are evaluating whether a job candidate satisfies ONE specific eligibility
criterion, based only on the documents provided below.

CRITERION TO CHECK:
{criterion_description}

CANDIDATE DOCUMENTS (each section is marked with its source document name
and page number):
---
{document_context}
---

Return ONLY valid JSON, no markdown formatting, no backticks, no extra text.
Use exactly this shape:

{{
  "result": "pass" | "fail" | "uncertain",
  "citation": {{
    "document": "<the DOCUMENT name from the marker that supports your answer, or null if none found>",
    "page": <the PAGE number from the marker, or null if none found>
  }},
  "reasoning": "<one or two sentence explanation of why you reached this result>"
}}

Rules:
- Base your answer ONLY on what's explicitly stated in the documents. Do not
  assume or infer qualifications that aren't written down.
- "pass" means the documents clearly show the candidate meets this criterion.
- "fail" means the documents clearly show the candidate does NOT meet it.
- "uncertain" means the documents don't have enough information to decide
  either way -- in this case, citation can be null.
- IMPORTANT: distinguish between "information is simply absent" and "a
  complete record exists but doesn't include this qualification". If a
  document appears to be a COMPLETE record for a category -- e.g. a
  resume's education section that lists degrees from school through the
  highest qualification held, or a full work history -- and the specific
  requirement in question (e.g. a particular degree, certification, or
  type of experience) is not mentioned anywhere in that complete record,
  treat this as "fail", not "uncertain". The absence of a qualification
  in an otherwise complete listing is evidence the candidate does not
  hold it. Reserve "uncertain" for cases where the relevant section is
  missing entirely, cut off, or the documents don't cover that topic at
  all.
- A resume/CV statement is the candidate's own claim, not proof. If the
  criterion concerns a formal qualification (a degree, certificate,
  category, date of birth) and only the resume mentions it -- with no
  supporting document (certificate, letter, official record) anywhere in
  the context -- return "uncertain" and start the reasoning with
  "Document incomplete:", naming the missing proof.
- A marksheet is NOT a degree: school (10th/12th) or semester/year
  marksheets prove examination marks, not that a college degree was
  completed and awarded -- only a degree/provisional/convocation
  certificate proves that. A degree-level criterion backed only by
  marksheets is "uncertain" ("Document incomplete:", naming the missing
  degree certificate).
- The citation MUST point to the specific document and page where you found
  the supporting (or contradicting) evidence.
"""


class GeminiParsingError(Exception):
    """Raised when the Gemini call fails even after all retries, or the
    response isn't valid JSON."""
    pass


def evaluate_criterion_with_gemini(
    document_context: str, criterion_description: str, max_attempts: int = 4
) -> dict:
    """
    Evaluates ONE criterion against a candidate's document context.

    Returns {"result": "pass"/"fail"/"needs_review", "citation": {"document":
    ..., "page": ...}, "reasoning": ...}. Gemini's "uncertain" is normalized
    to "needs_review" here, so the rest of the system only ever has to deal
    with one consistent vocabulary (matching the rule-based age check's
    "needs_review" outcome too).
    """
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    client = _get_client()
    prompt = CRITERION_EVALUATION_PROMPT_TEMPLATE.format(
        criterion_description=criterion_description,
        document_context=document_context,
    )

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            result = json.loads(raw)

            # Defensive normalization -- Gemini occasionally returns
            # "citation": null instead of a dict with null fields.
            if not isinstance(result.get("citation"), dict):
                result["citation"] = {"document": None, "page": None}
            else:
                result["citation"].setdefault("document", None)
                result["citation"].setdefault("page", None)

            if result.get("result") == "uncertain":
                result["result"] = "needs_review"

            return result

        except json.JSONDecodeError as e:
            last_error = e
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini did not return a valid response even after {max_attempts} attempts: {last_error}"
    )


BATCH_CRITERIA_EVALUATION_PROMPT_TEMPLATE = """
You are evaluating whether a job candidate satisfies EACH of the eligibility
criteria listed below, based only on the documents provided. Evaluate every
criterion INDEPENDENTLY -- one criterion's result must not influence another's.
Each criterion is tagged with its TYPE in [brackets] -- type-specific rules
below tell you exactly how to evaluate each type.

TODAY'S DATE: {today} -- use this for all date arithmetic (e.g. computing
the duration of a job listed as "present" / ongoing).

CRITERIA TO CHECK (numbered, each tagged with its type):
{criteria_list}

CANDIDATE'S DECLARED APPLICATION DATA (what the candidate claimed on their
application form / Excel roster -- claims, NOT proof):
---
{declared_data}
---

CANDIDATE'S CV/RESUME (ALSO the candidate's own claims, NOT proof -- written
by the candidate themselves):
---
{cv_context}
---

CANDIDATE DOCUMENTS (each section is marked with its source document name
and page number -- this is the PROOF):
---
{document_context}
---

EVERY criterion is verified in TWO STAGES:
  STAGE 1 -- DECLARED vs JD: does the candidate's declared application data
  satisfy the criterion? When the application data says NOTHING about a
  fact the criterion needs (a qualification, a job, a skill), fall back to
  the CV/resume: a claim made there counts as a declaration for stage 1.
  The CV never outranks the application data -- it only fills gaps.
  STAGE 2 -- DOCUMENTS vs DECLARED: do the candidate's documents actually
  prove what was declared (same qualification, same dates, same values)?
  This stage applies EQUALLY to claims that came from the CV: a CV
  statement is never its own proof.
"pass" requires BOTH stages to hold. A declaration that doesn't satisfy the
JD is a "fail" regardless of what the documents say. When the declaration
DOES satisfy the JD, stage 2 decides:
  - the documents CONTRADICT the declaration (different degree, different
    dates, different values) -> "fail".
  - the documents PROVE the declaration -> "pass".
  - the claim appears only in the CV/resume or application data, and the
    supporting document that would actually prove it (degree certificate,
    category certificate, experience letter, official record) is nowhere in
    the documents -> "uncertain", NOT "fail". A resume is the candidate's
    own claim, not proof -- but a claim deserves the chance to be proven,
    so route it to manual review instead of rejecting. Start the reasoning
    with "Document incomplete:" and name the missing proof.
([experience] and [skill] criteria override this with their own type-specific
rules below.) The reasoning MUST cover both stages explicitly.

Return ONLY valid JSON, no markdown formatting, no backticks, no extra text.
Return a JSON array containing EXACTLY one entry per criterion above, in the
same order, using exactly this shape:

[
  {{
    "index": <the criterion's number from the list above>,
    "result": "pass" | "fail" | "uncertain",
    "match_percentage": <integer 0-100 for [experience] and [skill] criteria; null for every other type>,
    "documented_years": <[experience] criteria only: the total in-field years you counted, as a number with up to 1 decimal; null for other types>,
    "required_years": <[experience] criteria only: the years the criterion requires, as a number; null for other types>,
    "skill_matches": <[skill] criteria only: one object per numbered skill (S1, S2, ...) listed under the criterion, see the [skill] rules; null for other types>,
    "citation": {{
      "document": "<the DOCUMENT name from the marker that supports your answer, or null if none found>",
      "page": <the PAGE number from the marker, or null if none found>
    }},
    "reasoning": "<explanation of why you reached this result -- see the type-specific rules for what it must contain>"
  }}
]

TYPE-SPECIFIC RULES:

[experience] -- the criterion states a required TOTAL number of years,
usually IN A SPECIFIC FIELD ("5 years of product management experience",
"2 years owning a B2C mobile application"). The years must be in that
field: judge each job's field from its title, role description, and
responsibilities in the documents. A job in an unrelated field contributes
ZERO years toward this criterion. If the criterion names no particular
field ("5 years of work experience"), then all documented experience
counts. Do the math, don't estimate:
  1. STAGE 1: check the experience the candidate DECLARED in their
     application data against the criterion -- both the number of years
     and the field. If the application data says nothing about work
     experience, the CV's work history serves as the declaration
     (still the candidate's claims, not proof).
  2. STAGE 2: verify EVERY declared job/employment period against the
     documents. A period counts as DOCUMENTED only when an uploaded
     experience/relieving certificate from that company states BOTH the
     joining date AND the resign/relieving date. A resume/CV work-history
     entry, a salary slip, or a joining letter alone is NOT sufficient
     proof. ONE exception: for the candidate's CURRENT employer (their
     most recent job, declared as ongoing), a joining letter alone IS
     acceptable -- treat that job as running from its joining date until
     today.
  3. Decide for each documented job whether its role matches the
     criterion's field. Compute each MATCHING period's duration, then SUM
     them into total in-field documented experience. Count overlapping
     periods only once.
  4. "match_percentage" = round((documented in-field years / required
     years) x 100), capped at 100. E.g. 4 in-field years against 5
     required = 80. Also return those two numbers as "documented_years" and
     "required_years" (e.g. 4.0 and 5), exactly the figures the percentage
     was computed from.
  5. "result": "pass" if documented in-field years >= the required years.
     Otherwise:
       - "uncertain" if one or more declared in-field periods were
         excluded ONLY because their proof was missing or incomplete (no
         certificate at all, or a certificate/joining letter without the
         resign date for a past employer), AND counting those declared
         periods would meet the requirement. Start the reasoning with
         "Document incomplete:" and name each such job and what proof is
         missing.
       - "fail" in every other case -- the declared experience itself
         doesn't satisfy the criterion, or the documented shortfall isn't
         caused by missing/incomplete documents (e.g. jobs in an
         unrelated field).
  6. The reasoning MUST show the calculation, explicitly saying which jobs
     counted as in-field and which were excluded and why, e.g.:
     "Org A (Product Manager, Jan 2015 - Jun 2018) = 3.4 yrs, counted;
     Org B (Systems Engineer, Jul 2018 - present) -- excluded, not product
     management; total in-field = 3.4 yrs < 5 required." When declared
     periods were excluded for missing/unreadable dates, say so too.

[skill] -- the JD's skills, already split into numbered items (S1, S2,
...) under the criterion. Your ONLY job per item is to CLASSIFY how the
closest skill the candidate shows compares with it -- the system turns the
level into marks, so never give marks or a percentage yourself:
  - "same": the candidate names the same skill -- identical, or a
    spelling/naming variant ("PowerBI" = "Power BI", "MS Excel" = "Excel",
    "Postgres" = "PostgreSQL").
    ALSO "same": the candidate's skill is a specific tool, library or
    dialect that is PART OF / BUILT ON the JD's broader skill, because using
    it means using that skill. JD "Python", candidate "Pandas" -> same.
    JD "SQL", candidate "MySQL" -> same. JD "Machine learning", candidate
    "scikit-learn" -> same.
  - "related": a DIFFERENT skill that does the same job and transfers with
    little training -- e.g. "Tableau" for "Power BI", "C++" for "Java",
    "PostgreSQL" for "MySQL", "GCP" for "AWS". Also the REVERSE of the
    "same" case above: the JD asks for the specific tool and the candidate
    only has the broader skill (JD "Pandas", candidate "Python" -> related).
  - "none": nothing comparable, or only a loosely connected area ("Excel"
    for "Python", "HTML" for "Java", "managed projects" for "Agile/Scrum
    with Jira", working at "an infrastructure company" for "road/highway
    sector experience"). When in doubt between two levels, pick the LOWER.
Read the skills from the declared application data AND the CV/resume (and
any documents). For each item return:
  {{"skill": <the item's number, e.g. 1 for S1>,
    "level": "same" | "related" | "none",
    "candidate_skill": "<the candidate's skill you compared, as they wrote it; null for none>",
    "source": "sheet" | "resume" | "both" | null  (where that skill appears: "sheet" = declared application data, "resume" = CV/resume or documents),
    "reason": "<one short line, e.g. 'Tableau is a BI tool like Power BI'>"}}
Every numbered item must appear exactly once in "skill_matches".
"result" MUST be "pass" and "match_percentage" null -- the system scores
skills. The reasoning briefly summarises the strongest matches and what is
missing.

[education] / [age] / [other] -- pass/fail/uncertain as usual, applying the
two-stage check: the declared qualification must satisfy the criterion AND
the documents must prove that declared qualification (same degree, same
institution details, same values). A mismatch between declaration and
documents is a "fail". A declaration that satisfies the criterion but is
backed only by the resume -- the actual proof document being missing -- is
"uncertain" with the reasoning prefixed "Document incomplete:", per the
stage rules above.
  A MARKSHEET IS NOT A DEGREE: a school marksheet (10th/12th) or a
  university semester/year marksheet only proves marks in an examination,
  NOT that a college degree was completed and awarded. Only a degree
  certificate, provisional degree certificate, or convocation/consolidated
  degree certificate proves graduation or post-graduation. Never accept a
  10th/12th marksheet as proof of ANY college qualification. If a
  degree-level criterion is backed only by marksheets, treat the actual
  proof as missing -> "uncertain", with the reasoning prefixed
  "Document incomplete:" naming the missing degree certificate.

GENERAL RULES (every criterion):
- Base your answer ONLY on what's explicitly stated in the documents. Do not
  assume or infer qualifications that aren't written down.
- "pass" means the documents clearly show the candidate meets the criterion.
- "fail" means the documents clearly show the candidate does NOT meet it.
- "uncertain" means the documents don't have enough information to decide
  either way -- in this case, citation fields can be null.
- IMPORTANT: distinguish between "information is simply absent" and "a
  complete record exists but doesn't include this qualification". If a
  document appears to be a COMPLETE record for a category -- e.g. a
  resume's education section that lists degrees from school through the
  highest qualification held, or a full work history -- and the specific
  requirement in question (e.g. a particular degree, certification, or
  type of experience) is not mentioned anywhere in that complete record,
  treat this as "fail", not "uncertain". The absence of a qualification
  in an otherwise complete listing is evidence the candidate does not
  hold it. Reserve "uncertain" for cases where the relevant section is
  missing entirely, cut off, or the documents don't cover that topic at
  all.
- Each entry's citation MUST point to the specific document and page where
  you found the supporting (or contradicting) evidence for THAT criterion.
- When your reasoning draws on MORE THAN ONE document (e.g. summing
  experience across several certificates), name EVERY document you used in
  the reasoning text, using its exact DOCUMENT name from the markers -- the
  citation field fits only one, so the reasoning must credit the rest.
"""


# Appended to the batch prompt for departments that collect NO proof
# documents (evidence_mode "declared_primary"). It overrides the two-stage
# "documents prove the declaration" rules: the application row is the
# evidence, the resume corroborates it.
DECLARED_PRIMARY_OVERRIDE = """

EVIDENCE-MODE OVERRIDE (takes priority over every rule above that talks
about proof documents, certificates, marksheets or experience letters):
This department does NOT collect proof documents. The candidate's DECLARED
APPLICATION DATA is the primary evidence and the CV/RESUME corroborates it.
  - A criterion is "pass" when the declared data satisfies it and the
    resume (if provided) does not contradict it.
  - NEVER return "uncertain" merely because a certificate, marksheet or
    experience letter is absent -- none are collected. Do not write
    "Document incomplete:".
  - "uncertain" is only for real doubt: the declared data and the resume
    CONTRADICT each other, or the facts needed are missing/unreadable in
    both. "fail" when the declared data (confirmed or not contradicted by
    the resume) does not satisfy the criterion.
  - [experience]: take every job period (organisation, designation, dates)
    from the declared data, falling back to / cross-checking against the
    resume. Count ONLY periods in roles relevant to the criterion's field
    (judge by designation and responsibilities); roles in unrelated fields
    count zero. Sum the matching periods, counting overlaps once. The
    reasoning MUST list every job as counted or excluded (with why) and
    show the total versus the required years. If a declared "total
    experience" figure disagrees with the sum of the listed periods by
    more than a few months, say so in the reasoning.
  - [education]: the declared degree and discipline are accepted as stated
    unless the resume contradicts them. Judge whether the degree/discipline
    satisfies the criterion (e.g. a listed equivalent field counts).
  - [skill]: classify each skill against the declared data AND the resume together.
"""


def _criterion_line(number: int, criterion: dict) -> str:
    """One numbered line of the batch prompt's criteria list. A skill
    criterion also lists its individual skills (S1, S2, ...) to classify."""
    line = f"{number}. [{criterion['type']}] {criterion['description']}"
    items = criterion.get("skill_items") or []
    if criterion["type"] == "skill" and items:
        line += "\n   Skills to classify: " + "; ".join(f"S{n}. {name}" for n, name in enumerate(items, start=1))
    return line


def _normalize_skill_matches(entry: dict, idx: int, item_count: int) -> list[dict]:
    """One {"level", "candidate_skill", "source", "reason"} per skill item,
    in item order. Raises ValueError when an item is missing or the level is
    unknown (the batch is retried)."""
    by_number: dict[int, dict] = {}
    for match in entry.get("skill_matches") or []:
        if not isinstance(match, dict):
            continue
        number = match.get("skill")
        if isinstance(number, str) and number.upper().lstrip("S").isdigit():
            number = int(number.upper().lstrip("S"))
        level = str(match.get("level") or "").strip().lower()
        if not isinstance(number, int) or not (1 <= number <= item_count) or level not in ("same", "related", "none"):
            continue
        source = str(match.get("source") or "").strip().lower()
        by_number[number] = {
            "level": level,
            "candidate_skill": (str(match.get("candidate_skill") or "").strip() or None) if level != "none" else None,
            "source": source if source in ("sheet", "resume", "both") and level != "none" else None,
            "reason": str(match.get("reason") or "").strip() or None,
        }
    if len(by_number) != item_count:
        raise ValueError(f"skill criterion {idx} classified {len(by_number)} of {item_count} skills")
    return [by_number[n] for n in range(1, item_count + 1)]


def _normalize_batch_results(parsed, criterion_types: list[str], skill_counts: list[int] | None = None) -> list[dict]:
    """
    Validates + normalizes a batch evaluation response. Raises ValueError
    if the response doesn't cover every criterion exactly once -- treated
    as a failed attempt by the caller (retried).

    `criterion_types` gives the type of each criterion (in prompt order) so
    experience entries can be held to their special contract: a match
    percentage (documented years vs required years) plus pass/fail/
    needs_review -- needs_review meaning the shortfall is caused purely by
    missing/incomplete proof documents (e.g. a certificate without a resign
    date), which HR must resolve manually.
    """
    expected_count = len(criterion_types)
    if not isinstance(parsed, list):
        raise ValueError("batch response is not a JSON array")

    by_index: dict[int, dict] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            raise ValueError("batch response entry is not an object")
        idx = entry.get("index")
        if not isinstance(idx, int) or not (1 <= idx <= expected_count):
            raise ValueError(f"batch response has invalid criterion index: {idx!r}")

        # Same defensive normalization as the single-criterion path.
        if not isinstance(entry.get("citation"), dict):
            entry["citation"] = {"document": None, "page": None}
        else:
            entry["citation"].setdefault("document", None)
            entry["citation"].setdefault("page", None)

        if entry.get("result") == "uncertain":
            entry["result"] = "needs_review"
        if entry.get("result") not in ("pass", "fail", "needs_review"):
            raise ValueError(f"batch response has invalid result for criterion {idx}")

        criterion_type = criterion_types[idx - 1]
        if criterion_type == "skill":
            # Gemini only classifies each skill; the marks and percentage
            # are computed by candidate_evaluation from the fixed marks and
            # HR's weights. Skills never reject here (any threshold gating
            # is applied by candidate_evaluation).
            item_count = skill_counts[idx - 1] if skill_counts else 0
            entry["skill_matches"] = _normalize_skill_matches(entry, idx, item_count) if item_count else []
            entry["match_percentage"] = None
            entry["result"] = "pass"
        elif criterion_type == "experience":
            pct = entry.get("match_percentage")
            if isinstance(pct, float):
                pct = round(pct)
            if not isinstance(pct, int):
                raise ValueError(f"experience criterion {idx} is missing match_percentage")
            entry["match_percentage"] = max(0, min(100, pct))
            for key in ("documented_years", "required_years"):
                value = entry.get(key)
                entry[key] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            # "needs_review" is allowed for experience: it means declared
            # periods were excluded only because their proof was missing or
            # incomplete (e.g. a certificate without a resign date for a
            # past employer) -- HR must check the documents manually.
        else:
            entry["match_percentage"] = None

        by_index[idx] = entry

    if len(by_index) != expected_count:
        raise ValueError(
            f"batch response covered {len(by_index)} criteria, expected {expected_count}"
        )
    return [by_index[i] for i in range(1, expected_count + 1)]


def evaluate_criteria_batch_with_gemini(
    document_context: str,
    criteria: list[dict],
    declared_data: str = "",
    cv_context: str = "",
    max_attempts: int = 4,
    evidence_mode: str = "documents_primary",
) -> list[dict]:
    """
    Evaluates ALL of a candidate's non-age criteria in ONE Gemini call,
    instead of one call per criterion -- the document context (by far the
    bulk of the prompt) is sent once instead of once per criterion.

    `criteria` is a list of {"type": ..., "description": ...} dicts. The
    type drives how each criterion is judged: experience criteria sum the
    candidate's DOCUMENTED job periods (proof = an experience certificate
    with both joining and resign dates; a joining letter alone counts only
    for the current employer, running until today) and compare the total
    against the required years (a percentage). Declared periods whose proof
    is missing or incomplete don't count -- they yield "needs_review"
    ("Document incomplete") when they are what stands between the candidate
    and a pass, and "fail" otherwise.

    Returns one result dict per criterion, in the same order as `criteria`,
    each shaped like evaluate_criterion_with_gemini()'s return value plus a
    "match_percentage" key (an int for experience criteria, None otherwise).

    If Gemini can't produce a valid batch response after all retries, falls
    back to the proven one-call-per-criterion path rather than failing the
    candidate outright.
    """
    if not criteria:
        return []
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    criterion_types = [c["type"] for c in criteria]
    skill_counts = [len(c.get("skill_items") or []) if c["type"] == "skill" else 0 for c in criteria]
    criteria_list = "\n".join(_criterion_line(i, c) for i, c in enumerate(criteria, start=1))
    prompt = BATCH_CRITERIA_EVALUATION_PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        criteria_list=criteria_list,
        declared_data=declared_data or "(no declared application data available)",
        cv_context=cv_context or "(no CV/resume provided)",
        document_context=document_context or "(no proof documents -- this department collects none)",
    )
    if evidence_mode == "declared_primary":
        prompt += DECLARED_PRIMARY_OVERRIDE
    client = _get_client()

    batch_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            return _normalize_batch_results(json.loads(raw), criterion_types, skill_counts)

        except (json.JSONDecodeError, ValueError):
            pass  # malformed/incomplete batch response -- retry
        except Exception as e:
            batch_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, batch_error)

    # Fallback: the slower but battle-tested single-criterion path. The
    # single-criterion prompt has no percentage contract, so experience and
    # skill criteria keep their hard rules but lose the percentage (None).
    fallback_results = []
    for criterion in criteria:
        result = evaluate_criterion_with_gemini(document_context, criterion["description"])
        result["match_percentage"] = None
        if criterion["type"] == "skill":
            result["result"] = "pass"  # skills never reject
        fallback_results.append(result)
    return fallback_results


CV_CERTIFICATIONS_PROMPT_TEMPLATE = """
You are reading a job candidate's CV/resume for a recruitment screening
system. Your ONLY task is to list every CERTIFICATE / CERTIFICATION the
candidate mentions.

CANDIDATE'S CV/RESUME:
---
{cv_context}
---

WHAT COUNTS AS A CERTIFICATE (include ALL of these):
- Professional certifications (e.g. CEH, CISSP, CISA, CISM, OSCP, CompTIA
  Security+, PMP, PRINCE2, ITIL, Six Sigma, CFA, CA, CPA ...)
- Vendor / technology certifications (e.g. AWS Certified Solutions
  Architect, Microsoft Azure certifications, Cisco CCNA/CCNP, Google Cloud,
  Oracle, Red Hat, Salesforce, SAP ...)
- Training / course completion certificates (NPTEL, Coursera, Udemy,
  edX, university short courses, government/PSU training programmes ...)
- Licences and registrations (e.g. professional engineer licence, bar
  registration) and certified memberships (e.g. ISACA, (ISC)2, IEEE).
- Certificates listed anywhere in the CV: a "Certifications" section,
  inside education, inside a job description, or in achievements.

WHAT IS NOT A CERTIFICATE (exclude):
- Academic degrees and school qualifications (10th, 12th, Diploma, B.Tech,
  B.E., MBA, M.Tech, PhD ...). Those are qualifications, not certificates.
- Plain skills or tools listed without any certificate (e.g. "Python",
  "Excel", "Wireshark").
- Awards, prizes, scholarships, publications, and job titles.

RULES:
- Base your answer ONLY on what is written in the CV. Do not invent
  certificates or assume ones that are not mentioned.
- Keep the certificate name as written in the CV (expand a bare acronym
  only when the expansion is unambiguous, e.g. "CEH (Certified Ethical
  Hacker)").
- List each distinct certificate ONCE, even if mentioned several times.
- If the CV mentions no certificates at all, return an empty array.

Return ONLY valid JSON, no markdown formatting, no backticks, no extra
text, using exactly this shape:

{{
  "certifications": [
    {{
      "name": "<certificate name as written in the CV>",
      "issuer": "<issuing body / platform if stated, else null>",
      "year": "<year or date if stated, else null>"
    }}
  ]
}}
"""


def _normalize_cv_certifications(parsed) -> list[dict]:
    """
    Validates + normalizes the certification extraction response into a
    clean list of dicts. Raises ValueError when the shape is wrong (the
    caller treats that as a failed attempt and retries).
    """
    if isinstance(parsed, list):
        items = parsed  # tolerate a bare array
    elif isinstance(parsed, dict) and isinstance(parsed.get("certifications"), list):
        items = parsed["certifications"]
    else:
        raise ValueError("certification response has no 'certifications' array")

    normalized: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("certification entry is not an object")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        def _opt_text(value) -> Optional[str]:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        normalized.append({
            "name": name,
            "issuer": _opt_text(item.get("issuer")),
            "year": _opt_text(item.get("year")),
        })
    return normalized


def extract_cv_certifications_with_gemini(cv_context: str, max_attempts: int = 3) -> list[dict]:
    """
    Lists every certificate/certification mentioned in a candidate's CV and
    flags each one as cyber-security related or not. Runs as its own small
    Gemini call during screening (only the CV text is sent, not the full
    document bundle), so it never disturbs the criteria evaluation
    response contract.

    Returns a list of {"name", "issuer", "year", "is_cyber_security",
    "reason"} dicts -- [] when the CV lists no certificates. Raises
    GeminiParsingError if no valid response comes back after all retries.
    """
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    client = _get_client()
    prompt = CV_CERTIFICATIONS_PROMPT_TEMPLATE.format(cv_context=cv_context)

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = (response.text or "").strip()

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            return _normalize_cv_certifications(json.loads(raw))

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e  # malformed response -- retry
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini did not return a valid certification list after {max_attempts} attempts: {last_error}"
    )


RESUME_CONSISTENCY_PROMPT_TEMPLATE = """You are cross-checking what a job applicant DECLARED in their application
form (the roster row) against what their RESUME says. You are looking for
contradictions, not judging suitability.

ITEMS TO CHECK:
1. Total work experience (years) and the employers / roles / dates behind it.
2. Each MUST-HAVE (essential) requirement below -- compare what the roster
   declares for it with what the resume shows.

MUST-HAVE REQUIREMENTS:
{must_haves}

ROSTER (declared application data):
{declared_data}

RESUME:
{cv_context}

For every item give a verdict:
- "consistent": roster and resume agree (small rounding, e.g. 4 vs 4.5 years, is fine).
- "inconsistent": they clearly disagree (different years, employer, degree,
  institution, or the roster claims something the resume contradicts).
- "unverified": one side does not mention it, so it cannot be compared.

RULES:
- Base answers ONLY on the text above. Never invent facts.
- Experience years: add up the dated roles in the resume when a total is not
  stated, and say so in the note.
- Keep each note to one short sentence naming both values.

Return ONLY valid JSON, no markdown, no backticks, using exactly this shape:

{{
  "checks": [
    {{
      "item": "<'Total experience' or the must-have requirement>",
      "roster": "<what the roster declares, or null>",
      "resume": "<what the resume shows, or null>",
      "verdict": "consistent" | "inconsistent" | "unverified",
      "note": "<one short sentence>"
    }}
  ]
}}
"""


def _normalize_resume_consistency(parsed) -> dict:
    """Validates the consistency response; raises ValueError on a wrong shape
    (the caller retries). Derives `overall` from the individual verdicts."""
    if isinstance(parsed, dict) and isinstance(parsed.get("checks"), list):
        items = parsed["checks"]
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError("consistency response has no 'checks' array")

    def _opt(value) -> Optional[str]:
        text = None if value is None else str(value).strip()
        return text or None

    checks = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("consistency check is not an object")
        verdict = str(item.get("verdict") or "").strip().lower()
        if verdict not in ("consistent", "inconsistent", "unverified"):
            verdict = "unverified"
        checks.append({
            "item": _opt(item.get("item")) or "Item",
            "roster": _opt(item.get("roster")),
            "resume": _opt(item.get("resume")),
            "verdict": verdict,
            "note": _opt(item.get("note")),
        })

    verdicts = {c["verdict"] for c in checks}
    overall = (
        "inconsistent" if "inconsistent" in verdicts
        else "consistent" if "consistent" in verdicts
        else "unverified"
    )
    return {"overall": overall, "checks": checks}


def check_resume_roster_consistency_with_gemini(
    declared_data: str, cv_context: str, must_haves: list[str], max_attempts: int = 3
) -> dict:
    """
    Compares the roster's declared experience and must-have items with the
    resume. Own small Gemini call (roster text + CV text only), so it never
    touches the criteria evaluation contract. Raises GeminiParsingError when
    no valid response comes back after all retries.
    """
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    client = _get_client()
    prompt = RESUME_CONSISTENCY_PROMPT_TEMPLATE.format(
        must_haves="\n".join(f"- {m}" for m in must_haves) or "- (none)",
        declared_data=declared_data or "(empty)",
        cv_context=cv_context,
    )

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return _normalize_resume_consistency(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini did not return a valid consistency check after {max_attempts} attempts: {last_error}"
    )


GOV_EXPERIENCE_PROMPT_TEMPLATE = """
You are reviewing a job candidate's work history for a government
recruitment screening system. List EVERY job the candidate has held and
classify each one. You are not judging suitability.

THE POST BEING FILLED:
{post_summary}

DECLARED APPLICATION DATA (the candidate's form / roster row):
{declared_data}

CV / RESUME:
{cv_context}

For each job decide two things:
1. "is_government": true when the EMPLOYER is government or GovTech:
   - a central / state / local government ministry, department,
     directorate, municipal body or the armed forces;
   - a public sector undertaking (PSU) or government-owned company, a
     statutory or autonomous government body or regulator;
   - a GovTech organisation whose main business is building technology or
     digital services for government (e.g. NIC, NeGD, CSC e-Governance,
     state e-governance societies), or a role the CV states was spent
     working ON a government project or deployment.
   A private company with ordinary private-sector clients is false.
2. "role_relevant": true when the ROLE itself (designation and duties) is
   in the same field as the post above -- the same test used for counting
   relevant experience. An admin, clerical or unrelated role is false even
   inside a government body (e.g. "Administrative Officer, Ministry of X"
   for a Data Analyst post is is_government true, role_relevant false).

RULES:
- Use ONLY the text above; never invent jobs, employers or dates.
- Take jobs from the declared data first and add any extra ones from the CV.
- "period" is the dates as written (e.g. "Jan 2019 - Mar 2022"), or null.
- "reason" is one short line explaining both decisions.

Return ONLY valid JSON, no markdown, no backticks, using exactly this shape:

{{
  "jobs": [
    {{
      "organisation": "<employer>",
      "designation": "<role / job title, or null>",
      "period": "<dates as written, or null>",
      "is_government": true | false,
      "role_relevant": true | false,
      "reason": "<one short line>"
    }}
  ]
}}
"""


def _normalize_gov_experience(parsed) -> dict:
    """Validates the government-experience response; raises ValueError on a
    wrong shape (the caller retries). Derives `has_relevant` from the jobs:
    a job counts only when it is government AND role-relevant."""
    if isinstance(parsed, dict) and isinstance(parsed.get("jobs"), list):
        items = parsed["jobs"]
    elif isinstance(parsed, list):
        items = parsed
    else:
        raise ValueError("government experience response has no 'jobs' array")

    def _opt(value) -> Optional[str]:
        text = None if value is None else str(value).strip()
        return text or None

    jobs = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("government experience job is not an object")
        organisation = _opt(item.get("organisation"))
        if not organisation:
            continue
        jobs.append({
            "organisation": organisation,
            "designation": _opt(item.get("designation")),
            "period": _opt(item.get("period")),
            "is_government": item.get("is_government") is True,
            "role_relevant": item.get("role_relevant") is True,
            "reason": _opt(item.get("reason")),
        })
    return {
        "jobs": jobs,
        "has_relevant": any(j["is_government"] and j["role_relevant"] for j in jobs),
    }


def classify_government_experience_with_gemini(
    declared_data: str, cv_context: str, post_summary: str, max_attempts: int = 3
) -> dict:
    """
    Lists the candidate's jobs, each flagged government/GovTech and
    relevant-to-the-post. Own small Gemini call (roster text + CV text
    only). Raises GeminiParsingError when no valid response comes back.
    """
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    client = _get_client()
    prompt = GOV_EXPERIENCE_PROMPT_TEMPLATE.format(
        post_summary=post_summary,
        declared_data=declared_data or "(empty)",
        cv_context=cv_context or "(no CV/resume provided)",
    )

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            return _normalize_gov_experience(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini did not return a valid government experience check after {max_attempts} attempts: {last_error}"
    )


def parse_jd_with_gemini(jd_text: str, max_attempts: int = 4) -> dict:
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file or in the environment."
        )

    client = _get_client()
    prompt = PROMPT_TEMPLATE.format(jd_text=jd_text)

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GEMINI_GENERATION_CONFIG,
            )
            raw = response.text.strip()

            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            return json.loads(raw)

        except json.JSONDecodeError as e:
            # Gemini returned invalid JSON -- retrying may fix it
            last_error = e
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini did not return a valid response even after {max_attempts} attempts: {last_error}"
    )


DOCUMENT_TRANSCRIPTION_IMAGE_PROMPT = """
You are transcribing a scanned page of a candidate's document (marksheet,
degree certificate, experience letter, payslip, etc.) so its contents can
be used for automated screening. The scan may be rotated, low-resolution,
or have glare -- read it as carefully as a human reviewer would.

Transcribe ALL text visible in the image, faithfully and completely --
names, dates of birth, institution and board names, degree titles, marks,
employer names, job titles, employment start/end dates, amounts. Preserve
the reading order. Do NOT summarize, interpret, or add commentary. If a
word is illegible, write [illegible].

Return ONLY the transcribed plain text, nothing else. If the image contains
no readable text at all, return exactly: [no readable text]
"""


def transcribe_document_image_with_gemini(
    image_bytes: bytes, mime_type: str = "image/png", max_attempts: int = 3
) -> str:
    """
    OCR for scanned/image-based document pages: the rendered page image is
    sent to Gemini's vision capability and the full text transcript comes
    back. Used as a fallback when a PDF has no embedded text layer, so
    screening isn't blind to scanned marksheets/certificates/letters.
    """
    if not GEMINI_API_KEY:
        raise GeminiParsingError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in your .env file or environment."
        )

    from google.genai import types

    client = _get_client()
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, DOCUMENT_TRANSCRIPTION_IMAGE_PROMPT],
                config=GEMINI_GENERATION_CONFIG,
            )
            return (response.text or "").strip()
        except Exception as e:
            last_error = e
            if not _is_retryable(e):
                break

        if attempt < max_attempts:
            _sleep_before_retry(attempt, last_error)

    raise GeminiParsingError(
        f"Gemini transcription failed after {max_attempts} attempts: {last_error}"
    )
