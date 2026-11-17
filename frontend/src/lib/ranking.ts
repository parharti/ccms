import type { Candidate } from '../types';

/**
 * The result group a candidate is shown and ranked in. "Eligible with
 * exception" is not a stored status: it is a needs-review candidate tagged
 * strong_exception (misses the experience must-have by no more than the
 * tolerance, with strong skills). Mirrors the backend's result_group().
 */
export function resultGroup(c: Pick<Candidate, 'status' | 'review_tag'>): string {
  return c.status === 'needs_review' && c.review_tag === 'strong_exception' ? 'eligible_with_exception' : c.status;
}

// Best first, the same ordering as the backend's Results / Excel export:
// eligible, eligible with exception, needs review, not eligible, not
// screened; within a group only the suitability score decides, the skills
// match breaks exact ties. Tags (government etc.) never move a candidate.
// Stable, so remaining ties keep roster order.
const GROUP_ORDER: Record<string, number> = {
  eligible: 0,
  eligible_with_exception: 1,
  needs_review: 2,
  not_eligible: 3,
  not_evaluated: 4,
};

const rankKey = (c: Candidate): number[] => [
  GROUP_ORDER[resultGroup(c)] ?? 9,
  -(c.suitability_score ?? -1),
  -(c.skill_match_percentage ?? -1),
];

export function rankCandidates(candidates: Candidate[]): Candidate[] {
  return [...candidates].sort((a, b) => {
    const ka = rankKey(a);
    const kb = rankKey(b);
    for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] - kb[i];
    return 0;
  });
}
