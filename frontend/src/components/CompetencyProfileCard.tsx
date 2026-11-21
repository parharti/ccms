import React from 'react';
import { Radar } from 'lucide-react';
import type { CandidateReviewDetail, JobProfile } from '../types';

interface Section {
  key: string;
  label: string;
  /** 0-100, null = could not be scored for this candidate. */
  value: number | null;
  weight: number;
  detail?: string | null;
  evidence?: string | null;
  source?: string | null;
}

/** Same rules as the backend's compute_section_scores / compute_suitability. */
function buildSections(review: CandidateReviewDetail, profile: JobProfile): Section[] {
  const skillPcts = review.evaluations
    .filter((e) => e.criterion_type === 'skill' && e.match_percentage != null)
    .map((e) => e.match_percentage as number);
  const points: Record<string, number> = { pass: 100, needs_review: 50, fail: 0 };
  const desirable = review.evaluations
    .filter((e) => !e.is_essential && (e.criterion_type === 'education' || e.criterion_type === 'other'))
    .map((e) => points[e.result] ?? 0);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

  const sections: Section[] = [
    { key: 'skills', label: 'Technical skills', value: avg(skillPcts), weight: profile.weight_skills ?? 40 },
    { key: 'desirable', label: 'Desirable items', value: avg(desirable), weight: profile.weight_desirable ?? 15 },
  ];
  const scores = new Map((review.competency_scores ?? []).map((s) => [s.key, s]));
  for (const comp of profile.competencies ?? []) {
    const s = comp.key ? scores.get(comp.key) : undefined;
    sections.push({
      key: comp.key ?? comp.name,
      label: comp.name,
      value: s ? s.score * 20 : null,
      weight: comp.weight,
      detail: s ? `${s.score} / 5${s.reason ? ` — ${s.reason}` : ''}` : null,
      evidence: s?.evidence,
      source: s?.document ? `${s.document}${s.page ? `, p. ${s.page}` : ''}` : null,
    });
  }
  return sections.filter((s) => s.weight > 0);
}

const RadarChart: React.FC<{ sections: Section[] }> = ({ sections }) => {
  const size = 300;
  const c = size / 2;
  const r = 96;
  const n = sections.length;
  const point = (i: number, v: number) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [c + Math.cos(a) * r * v, c + Math.sin(a) * r * v];
  };
  const ring = (v: number) => sections.map((_, i) => point(i, v).join(',')).join(' ');
  const shape = sections.map((s, i) => point(i, (s.value ?? 0) / 100).join(',')).join(' ');

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[320px] mx-auto" role="img" aria-label="Competency radar chart">
      {[0.2, 0.4, 0.6, 0.8, 1].map((v) => (
        <polygon key={v} points={ring(v)} fill="none" stroke="var(--border)" strokeWidth={1} />
      ))}
      {sections.map((_, i) => {
        const [x, y] = point(i, 1);
        return <line key={i} x1={c} y1={c} x2={x} y2={y} stroke="var(--border)" strokeWidth={1} />;
      })}
      <polygon points={shape} fill="var(--primary)" fillOpacity={0.18} stroke="var(--primary)" strokeWidth={2} strokeLinejoin="round" />
      {sections.map((s, i) => {
        const [x, y] = point(i, (s.value ?? 0) / 100);
        return <circle key={s.key} cx={x} cy={y} r={3.5} fill="var(--primary)" />;
      })}
      {sections.map((s, i) => {
        const [x, y] = point(i, 1.2);
        const anchor = Math.abs(x - c) < 8 ? 'middle' : x > c ? 'start' : 'end';
        return (
          <text key={s.key} x={x} y={y} textAnchor={anchor} dominantBaseline="middle" fontSize={11} fontWeight={600} fill="var(--foreground)">
            {s.label.length > 18 ? `${s.label.slice(0, 17)}…` : s.label}
          </text>
        );
      })}
    </svg>
  );
};

/**
 * The candidate's profile across every scored section -- skills, desirable
 * items and the post's competencies (projects, leadership, communication,
 * ...) -- as a radar chart plus a breakdown of how each section adds up to
 * the suitability score out of 100.
 */
export const CompetencyProfileCard: React.FC<{ review: CandidateReviewDetail; profile: JobProfile }> = ({ review, profile }) => {
  const sections = buildSections(review, profile);
  if (!sections.length || review.status === 'not_evaluated') return null;
  const scoredWeight = sections.filter((s) => s.value != null).reduce((a, s) => a + s.weight, 0);
  const totalWeight = sections.reduce((a, s) => a + s.weight, 0);
  const assessed = review.competency_scores != null;

  return (
    <div className="bg-card border border-border rounded-lg p-4 sm:p-6 shadow-sm flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Radar className="w-4.5 h-4.5 text-primary" />
          <h2 className="font-semibold text-base text-foreground">Competency profile</h2>
        </div>
        <span className="text-sm font-semibold text-foreground">
          Score <span className="text-2xl font-bold text-primary">{review.suitability_score ?? '—'}</span>
          <span className="text-muted"> / 100</span>
        </span>
      </div>

      {!assessed && (
        <p className="text-sm text-muted">
          Competencies are scored for eligible and needs-review candidates. Re-screen this candidate to score them.
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-[minmax(0,320px)_1fr] gap-6 items-start">
        {sections.length >= 3 ? <RadarChart sections={sections} /> : <div />}
        <ul className="flex flex-col gap-3 min-w-0">
          {sections.map((s) => {
            const share = totalWeight ? Math.round((s.weight / totalWeight) * 100) : 0;
            const pts = s.value != null && scoredWeight ? (s.value * s.weight) / scoredWeight : null;
            return (
              <li key={s.key} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-semibold text-foreground truncate">{s.label}</span>
                  <span className="text-muted shrink-0 tabular-nums">
                    {pts != null ? `${pts.toFixed(1)} pts` : 'not scored'} · weight {share}%
                  </span>
                </div>
                <div className="h-2 rounded-full bg-border/60 overflow-hidden">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${s.value ?? 0}%` }} />
                </div>
                {s.detail && <p className="text-xs text-foreground">{s.detail}</p>}
                {s.evidence && (
                  <p className="text-xs text-muted italic break-words">
                    “{s.evidence}”{s.source ? <span className="not-italic"> — {s.source}</span> : null}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
      </div>
      <p className="text-xs text-muted">
        Each competency is scored 0–5 only from concrete evidence in the candidate's documents (0 = none, 3 = clear
        example, 5 = sustained, measurable impact). Weights are set per post under Screening rules.
      </p>
    </div>
  );
};

export default CompetencyProfileCard;
