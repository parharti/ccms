import type { Candidate } from '../types';

// Best first, the same ordering as the backend's Results / Excel export:
// eligible, needs review, not eligible, not screened; government-tagged
// candidates lead their group, then strong-exception and close-miss ones;
// then suitability score, then skills match. Stable, so ties keep roster order.
const STATUS_ORDER: Record<string, number> = { eligible: 0, needs_review: 1, not_eligible: 2, not_evaluated: 3 };

const rankKey = (c: Candidate): number[] => [
  STATUS_ORDER[c.status] ?? 9,
  c.gov_tag ? 0 : 1,
  c.review_tag === 'strong_exception' || c.review_tag === 'close_miss' ? 0 : 1,
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
