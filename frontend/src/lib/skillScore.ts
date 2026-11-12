import type { SkillMark } from '../types';

export interface SkillScore {
  /** Points earned: the sum of mark × weight. */
  total: number;
  /** Points possible: the sum of the weights. */
  outOf: number;
  /** total / outOf as a percentage, unrounded. */
  pct: number;
  /** The skills section's marks out of the post's skills weight (e.g. 38.2 / 50). */
  sectionMarks: number | null;
  sectionWeight: number | null;
}

const round = (n: number, places: number) => Math.round(n * 10 ** places) / 10 ** places;

// Skills score = points / possible points, then scaled to the post's skills
// weight: e.g. 29 of 38 points = 76.3%, and 76.3% of a weight of 50 = 38.2 marks.
export function skillScore(marks: SkillMark[], sectionWeight?: number | null): SkillScore | null {
  const scored = marks.filter((m) => m.weight > 0);
  const outOf = scored.reduce((sum, m) => sum + m.weight, 0);
  if (!outOf) return null;
  const total = scored.reduce((sum, m) => sum + m.points, 0);
  const pct = (100 * total) / outOf;
  const weight = sectionWeight != null && sectionWeight > 0 ? sectionWeight : null;
  return {
    total: round(total, 2),
    outOf: round(outOf, 2),
    pct: round(pct, 1),
    sectionMarks: weight != null ? round((pct * weight) / 100, 1) : null,
    sectionWeight: weight,
  };
}

/** "29 / 38 = 76.3% → 38.2 / 50 marks" (the last part only when a weight is set). */
export function formatSkillScore(score: SkillScore): string {
  const base = `${score.total} / ${score.outOf} = ${score.pct}%`;
  return score.sectionMarks != null ? `${base} → ${score.sectionMarks} / ${score.sectionWeight} marks` : base;
}
