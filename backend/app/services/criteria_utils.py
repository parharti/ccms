"""
Small shared helpers for interpreting Gemini's raw criterion output into
DB-ready fields. Used by both the initial JD upload flow (jd_upload.py)
and the criteria restore flow (job_profiles.py), so the same heuristic
is applied consistently in both places.
"""

import re


def is_essential_from_description(description: str, criterion_type: str = "") -> bool:
    """Guesses essential vs desirable/preferred from the wording at the
    start of the description. A small heuristic -- HR can override this
    in the Criteria Editor if it's wrong.

    Skill criteria always default to NON-essential: the skills match is an
    informational percentage that never rejects a candidate unless HR
    explicitly marks it essential and sets a minimum match percentage.
    """
    if criterion_type == "skill":
        return False
    lowered = description.strip().lower()
    return not lowered.startswith(("preferred", "preferable", "desirable"))


def resolve_is_essential(criterion: dict) -> bool:
    """Must-have (True) vs soft (False) for one criterion dict from the JD
    parse. Gemini's "mandatory" flag -- set from the JD's own wording -- wins
    when present; otherwise fall back to the wording heuristic. Skills are
    always soft."""
    criterion_type = criterion.get("type", "other")
    if criterion_type == "skill":
        return False
    mandatory = criterion.get("mandatory")
    if isinstance(mandatory, bool):
        return mandatory
    return is_essential_from_description(criterion.get("description", ""), criterion_type)


# Marks a single JD skill earns, by how closely the candidate's skill
# matches it. Gemini only decides the level; the marks are fixed here so the
# same match always scores the same. "same" is always 1 and "none" 0; the
# "related" mark is HR's choice per post (0-1, 0.5 when not set). HR's
# per-skill weight (1 / 0.5 / 0) multiplies the mark.
DEFAULT_RELATED_MARK = 0.5
SKILL_WEIGHTS = (1.0, 0.5, 0.0)


def normalize_related_mark(value) -> float:
    """HR's mark for a related skill, clamped to 0-1 (0.5 when unset)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RELATED_MARK
    return min(1.0, max(0.0, value))


def skill_level_marks(related_mark=None) -> dict[str, float]:
    return {"same": 1.0, "related": normalize_related_mark(related_mark), "none": 0.0}

_SKILL_SPLIT = re.compile(r"[,;\n•]|\band\b", re.IGNORECASE)
_SKILL_LEAD = re.compile(
    r"^(?:(?:strong|good|solid|basic|working|hands-on|proven|excellent)\s+)*"
    r"(?:knowledge|understanding|proficiency|experience|familiarity|expertise|skills?)"
    r"\s+(?:of|in|with)\s+",
    re.IGNORECASE,
)


def split_skill_description(description: str) -> list[str]:
    """Best-effort split of a consolidated skill description into individual
    skills -- used when the JD parse didn't return a list (older profiles,
    HR-added criteria). HR can fix the list in the criteria editor."""
    items = []
    for part in _SKILL_SPLIT.split(description or ""):
        name = _SKILL_LEAD.sub("", part.strip(" .:-()")).strip(" .:-()")
        if name and name.lower() not in {i.lower() for i in items}:
            items.append(name)
    return items


def normalize_skill_items(items, description: str = "") -> list[dict]:
    """[{"name", "weight"}] with weights snapped to 1 / 0.5 / 0 and
    duplicates dropped. Accepts plain strings (weight 1). Falls back to
    splitting the description when no usable list is given."""
    result: list[dict] = []
    seen: set[str] = set()
    for item in items or []:
        if isinstance(item, str):
            name, weight = item, 1.0
        elif isinstance(item, dict):
            name, weight = item.get("name"), item.get("weight", 1.0)
        else:
            continue
        name = str(name or "").strip()
        if not name or name.lower() in seen:
            continue
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            weight = 1.0
        weight = min(SKILL_WEIGHTS, key=lambda w: abs(w - weight))
        seen.add(name.lower())
        result.append({"name": name, "weight": weight})
    if not result and description:
        result = [{"name": n, "weight": 1.0} for n in split_skill_description(description)]
    return result


def skill_items_from_parse(criterion: dict) -> list[dict] | None:
    """Skill list (all weight 1) for one criterion dict from the JD parse;
    None for every non-skill criterion."""
    if criterion.get("type") != "skill":
        return None
    return normalize_skill_items(criterion.get("skill_items"), criterion.get("description", ""))


def score_skill_matches(
    items: list[dict], matches: list[dict], related_mark=None
) -> tuple[list[dict], int | None]:
    """Turns Gemini's per-skill levels into fixed marks:
    mark = 1 (same) / HR's related mark / 0 (none), points = mark x HR's weight.
    Returns (skill_marks rows for storage, match % = points / weights),
    the % being None when no skill carries weight."""
    level_marks = skill_level_marks(related_mark)
    marks = []
    for item, match in zip(items, matches):
        mark = level_marks[match["level"]]
        marks.append({
            "skill": item["name"],
            "weight": item["weight"],
            "level": match["level"],
            "candidate_skill": match.get("candidate_skill"),
            "source": match.get("source"),
            "mark": mark,
            "points": mark * item["weight"],
            "reason": match.get("reason"),
        })
    total_weight = sum(m["weight"] for m in marks)
    if not total_weight:
        return marks, None
    return marks, round(100 * sum(m["points"] for m in marks) / total_weight)


def rescore_skill_marks(items: list[dict], saved_marks: list[dict], related_mark=None):
    """Re-scores saved skill marks with the post's CURRENT skill weights and
    related mark -- the levels Gemini gave are kept, so no new Gemini call.
    Returns (marks, pct), or None when a current skill was never classified
    (HR added it after screening -- only a re-screen can mark it)."""
    by_name = {str(m.get("skill") or "").lower(): m for m in saved_marks or []}
    if not items or any(i["name"].lower() not in by_name for i in items):
        return None
    return score_skill_matches(items, [by_name[i["name"].lower()] for i in items], related_mark)


def skill_score_summary(marks: list[dict]) -> str:
    """'Skills score 6.5 / 8: SQL 1, Power BI 0.5 (has Tableau), ...'"""
    scored = [m for m in marks if m["weight"]]
    total = sum(m["points"] for m in scored)
    out_of = sum(m["weight"] for m in scored)

    def part(m):
        text = f"{m['skill']} {m['points']:g}"
        if m["level"] == "related" and m.get("candidate_skill"):
            text += f" (has {m['candidate_skill']})"
        return text

    return f"Skills score {total:g} / {out_of:g}: " + ", ".join(part(m) for m in scored) + "."
