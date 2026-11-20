import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Printer } from 'lucide-react';
import { useCandidateReview } from '../../hooks/useReview';
import { useJobProfile } from '../../hooks/useJobProfile';
import { useCandidates } from '../../hooks/useCandidates';
import { ORG_NAME } from '../../lib/branding';
import { formatDateTime, statusLabel } from '../../lib/format';
import { rankCandidates } from '../../lib/ranking';
import { formatSkillScore, skillScore } from '../../lib/skillScore';
import type { CandidateReviewDetail, CriterionEvaluationDetail, SkillMark } from '../../types';

/**
 * Printable per-candidate reports (opened from the candidate page, printed
 * or saved as PDF with the browser's print dialog):
 *   hr    -- HR screening report: every criterion, every skill mark, the
 *            government experience check, the sheet-vs-resume check,
 *            overrides. The full audit trail.
 *   brief -- one-page brief for the hiring committee: profile, scores,
 *            skills matched / partial / missing and points to probe.
 *            Leaves out the mismatch check and HR overrides (HR-only).
 */
type ReportKind = 'hr' | 'brief';

const RESULT_TEXT: Record<string, string> = { pass: 'Met', fail: 'Not met', needs_review: 'Needs review' };
const LEVEL_TEXT: Record<SkillMark['level'], string> = { same: 'Same', related: 'Related', none: 'Not found' };
const SOURCE_TEXT: Record<string, string> = { sheet: 'Sheet', resume: 'Resume', both: 'Sheet + resume' };
// The panel brief never shows HR-only tags.
const HR_ONLY_TAGS = new Set(['data_mismatch']);

const Section: React.FC<{ title: string; children: React.ReactNode; className?: string }> = ({ title, children, className = '' }) => (
  <section className={`break-inside-avoid ${className}`}>
    <h2 className="text-sm font-bold uppercase tracking-wide text-primary border-b border-border pb-1 mb-2">{title}</h2>
    {children}
  </section>
);

const Th: React.FC<{ children?: React.ReactNode; right?: boolean }> = ({ children, right }) => (
  <th className={`py-1.5 pr-3 font-semibold text-foreground ${right ? 'text-right' : 'text-left'}`}>{children}</th>
);
const Td: React.FC<{ children?: React.ReactNode; right?: boolean; className?: string }> = ({ children, right, className = '' }) => (
  <td className={`py-1.5 pr-3 align-top ${right ? 'text-right' : ''} ${className}`}>{children}</td>
);

function skillMarks(review: CandidateReviewDetail): SkillMark[] {
  return review.evaluations.find((e) => e.criterion_type === 'skill')?.skill_marks ?? [];
}

// Interview focus points, built from the screening itself (no AI): the
// partial and missing skills, and any near-miss / exception note.
function probePoints(review: CandidateReviewDetail, marks: SkillMark[]): string[] {
  const points: string[] = [];
  if (review.review_tag && !HR_ONLY_TAGS.has(review.review_tag) && review.review_note) {
    points.push(review.review_note);
  }
  for (const m of marks.filter((m) => m.weight > 0 && m.level === 'related')) {
    points.push(`${m.skill}: has ${m.candidate_skill ?? 'a related skill'} instead. Ask how quickly they could work in ${m.skill}.`);
  }
  for (const m of marks.filter((m) => m.weight > 0 && m.level === 'none').sort((a, b) => b.weight - a.weight)) {
    points.push(`${m.skill}: no evidence in the sheet or resume. Check for hands-on experience.`);
  }
  return points.slice(0, 6);
}

export const CandidateReportPage: React.FC = () => {
  const { profileId, candidateId, kind } = useParams<{ profileId: string; candidateId: string; kind: string }>();
  const { data: review, isLoading } = useCandidateReview(profileId, candidateId);
  const { data: profile } = useJobProfile(profileId);
  const { data: candidates } = useCandidates(profileId);
  const reportKind: ReportKind = kind === 'brief' ? 'brief' : 'hr';

  if (isLoading) return <p className="p-5 sm:p-8 text-sm font-medium text-muted">Loading report…</p>;
  if (!review) return <p className="p-5 sm:p-8 text-sm font-medium text-danger">Candidate not found.</p>;

  const screened = candidates?.filter((c) => c.status !== 'not_evaluated') ?? [];
  const rankIndex = rankCandidates(screened).findIndex((c) => c.id === review.candidate_id);
  const rank = rankIndex >= 0 ? `${rankIndex + 1} of ${screened.length}` : '—';
  const marks = skillMarks(review);
  const skillWeight = profile?.weight_skills;
  const score = skillScore(marks, skillWeight);
  const relatedMark = profile?.criteria.find((c) => c.type === 'skill')?.related_mark ?? 0.5;
  const reportTitle = reportKind === 'hr' ? 'HR screening report' : 'Hiring committee brief';

  return (
    <div className="min-h-screen bg-background print:bg-white">
      {/* Toolbar (not printed) */}
      <div className="print:hidden sticky top-0 z-10 bg-card border-b border-border">
        <div className="max-w-[210mm] mx-auto px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <Link
            to={`/candidate/${profileId}/${candidateId}`}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-primary"
          >
            <ArrowLeft className="w-4 h-4" /> Back to candidate
          </Link>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/candidate/${profileId}/${candidateId}/print/${reportKind === 'hr' ? 'brief' : 'hr'}`}
              className="text-sm font-semibold px-4 py-2 rounded-lg border border-border text-foreground hover:border-primary/40"
            >
              {reportKind === 'hr' ? 'Switch to committee brief' : 'Switch to HR report'}
            </Link>
            <button
              onClick={() => window.print()}
              className="text-sm font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground flex items-center gap-2"
            >
              <Printer className="w-4 h-4" /> Print / save as PDF
            </button>
          </div>
        </div>
      </div>

      <article className="max-w-[210mm] mx-auto my-6 print:my-0 bg-white text-foreground shadow-sm print:shadow-none border border-border print:border-0 rounded-lg print:rounded-none px-4 py-5 sm:px-10 sm:py-8 print:px-0 print:py-0 flex flex-col gap-5 text-[13px] leading-snug">
        {/* Header */}
        <header className="flex flex-wrap items-start justify-between gap-3 sm:gap-6 border-b-2 border-primary pb-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">{ORG_NAME} · {reportTitle}</p>
            <h1 className="text-2xl font-bold text-foreground mt-1">{review.name || 'Unnamed candidate'}</h1>
            <p className="text-sm text-muted mt-0.5">
              {profile?.title ?? 'Post'}
              {review.external_id ? ` · ID ${review.external_id}` : ''}
            </p>
          </div>
          <div className="text-right text-xs text-muted shrink-0">
            <p>Generated {formatDateTime(new Date().toISOString())}</p>
          </div>
        </header>

        {/* Outcome strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 print:grid-cols-4 gap-3">
          <Stat label="Status" value={statusLabel(review.status)} />
          <Stat label="Rank" value={rank} />
          <Stat
            label="Skills score"
            value={score ? (score.sectionMarks != null ? `${score.sectionMarks} / ${score.sectionWeight}` : `${score.pct}%`) : '—'}
          />
          <Stat label="Suitability" value={review.suitability_score != null ? `${review.suitability_score} / 100` : '—'} />
        </div>
        {(review.gov_tag || (review.review_tag && (reportKind === 'hr' || !HR_ONLY_TAGS.has(review.review_tag)))) && (
          <div className="flex flex-wrap gap-2 -mt-2">
            {review.gov_tag && <Tag tone="primary">Government relevant experience</Tag>}
            {review.review_tag && (reportKind === 'hr' || !HR_ONLY_TAGS.has(review.review_tag)) && (
              <Tag tone="warning">{statusLabel(review.review_tag)}{review.review_note ? `: ${review.review_note}` : ''}</Tag>
            )}
          </div>
        )}

        {reportKind === 'hr' ? <HrReport review={review} marks={marks} skillWeight={skillWeight} relatedMark={relatedMark} /> : <PanelBrief review={review} marks={marks} />}
      </article>
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="border border-border rounded-md px-3 py-2">
    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</p>
    <p className="text-base font-bold text-foreground mt-0.5">{value}</p>
  </div>
);

const Tag: React.FC<{ tone: 'primary' | 'warning'; children: React.ReactNode }> = ({ tone, children }) => (
  <span
    className={`text-xs font-semibold px-2 py-1 rounded-md border ${
      tone === 'primary' ? 'border-primary/30 text-primary' : 'border-warning/40 text-warning'
    }`}
  >
    {children}
  </span>
);

const SkillTable: React.FC<{ marks: SkillMark[]; skillWeight?: number | null }> = ({ marks, skillWeight }) => {
  const score = skillScore(marks, skillWeight);
  return (
    <table className="w-full">
      <thead className="border-b border-border">
        <tr>
          <Th>JD skill</Th>
          <Th>Candidate has</Th>
          <Th>Match</Th>
          <Th>Found in</Th>
          <Th right>Mark × weight</Th>
          <Th right>Points</Th>
        </tr>
      </thead>
      <tbody>
        {marks.map((m) => (
          <tr key={m.skill} className="border-b border-border/60">
            <Td className="font-medium">{m.skill}</Td>
            <Td>
              {m.candidate_skill || '—'}
              {m.reason && <span className="block text-[11px] text-muted">{m.reason}</span>}
            </Td>
            <Td>{LEVEL_TEXT[m.level]}</Td>
            <Td>{m.source ? SOURCE_TEXT[m.source] ?? m.source : '—'}</Td>
            <Td right>{m.weight === 0 ? 'not scored' : `${m.mark} × ${m.weight}`}</Td>
            <Td right className="font-semibold">{m.weight === 0 ? '—' : m.points}</Td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={5} className="py-1.5 pr-3 text-right font-semibold">Skills score</td>
          <Td right className="font-bold">{score ? formatSkillScore(score) : '—'}</Td>
        </tr>
      </tfoot>
    </table>
  );
};

const HrReport: React.FC<{
  review: CandidateReviewDetail;
  marks: SkillMark[];
  skillWeight?: number | null;
  relatedMark: number;
}> = ({ review, marks, skillWeight, relatedMark }) => (
  <>
    {review.status_overridden && (
      <Section title="HR override">
        <p>
          AI decision: <strong>{statusLabel(review.computed_status)}</strong> → changed to{' '}
          <strong>{statusLabel(review.status)}</strong>
          {review.overridden_at ? ` on ${formatDateTime(review.overridden_at)}` : ''}.
        </p>
        {review.override_reason && <p className="text-muted mt-1">Reason: {review.override_reason}</p>}
      </Section>
    )}

    <Section title="Criteria">
      <table className="w-full">
        <thead className="border-b border-border">
          <tr>
            <Th>Criterion</Th>
            <Th>Result</Th>
            <Th>Evidence and reasoning</Th>
          </tr>
        </thead>
        <tbody>
          {review.evaluations.map((ev: CriterionEvaluationDetail) => (
            <tr key={ev.criterion_id} className="border-b border-border/60">
              <Td className="w-[32%]">
                <span className="text-[11px] font-semibold uppercase text-muted">
                  {ev.criterion_type}
                  {ev.is_essential ? ' · must-have' : ''}
                </span>
                <span className="block">{ev.criterion_description}</span>
              </Td>
              <Td className="whitespace-nowrap font-semibold">
                {ev.criterion_type === 'skill' && !ev.is_essential ? 'Scored' : RESULT_TEXT[ev.result] ?? ev.result}
                {typeof ev.match_percentage === 'number' && (
                  <span className="block font-normal text-muted">{ev.match_percentage}%</span>
                )}
              </Td>
              <Td>
                {ev.reasoning}
                {ev.citation_document && (
                  <span className="block text-[11px] text-muted mt-0.5">
                    Source: {ev.citation_document}
                    {ev.citation_page ? `, page ${ev.citation_page}` : ''}
                  </span>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>

    {marks.length > 0 && (
      <Section title="Skill marks">
        <p className="text-[11px] text-muted mb-1.5">
          Same skill = 1, related skill = {relatedMark}, not found = 0; multiplied by the weight HR set for each
          skill. Points ÷ possible points = skills %, and that % of the skills weight gives the marks.
        </p>
        <SkillTable marks={marks} skillWeight={skillWeight} />
      </Section>
    )}

    {review.gov_experience && (
      <Section title="Government relevant experience">
        <p className="text-[11px] text-muted mb-1.5">
          A job counts only when the employer is government / GovTech and the role is relevant to this post.
        </p>
        <table className="w-full">
          <thead className="border-b border-border">
            <tr>
              <Th>Job</Th>
              <Th>Period</Th>
              <Th>Government</Th>
              <Th>Relevant role</Th>
              <Th>Counts</Th>
            </tr>
          </thead>
          <tbody>
            {review.gov_experience.jobs.map((j, i) => (
              <tr key={i} className="border-b border-border/60">
                <Td>
                  {j.designation ? `${j.designation}, ` : ''}
                  {j.organisation}
                  {j.reason && <span className="block text-[11px] text-muted">{j.reason}</span>}
                </Td>
                <Td className="whitespace-nowrap">{j.period ?? '—'}</Td>
                <Td>{j.is_government ? 'Yes' : 'No'}</Td>
                <Td>{j.role_relevant ? 'Yes' : 'No'}</Td>
                <Td className="font-semibold">{j.is_government && j.role_relevant ? 'Yes' : 'No'}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    )}

    {review.resume_consistency && (
      <Section title="Sheet vs resume check">
        <table className="w-full">
          <thead className="border-b border-border">
            <tr>
              <Th>Item</Th>
              <Th>Sheet</Th>
              <Th>Resume</Th>
              <Th>Verdict</Th>
            </tr>
          </thead>
          <tbody>
            {review.resume_consistency.checks.map((c) => (
              <tr key={c.item} className="border-b border-border/60">
                <Td className="font-medium">
                  {c.item}
                  {c.note && <span className="block text-[11px] text-muted font-normal">{c.note}</span>}
                </Td>
                <Td>{c.roster ?? '—'}</Td>
                <Td>{c.resume ?? '—'}</Td>
                <Td className={`font-semibold ${c.verdict === 'inconsistent' ? 'text-danger' : ''}`}>
                  {c.verdict === 'inconsistent' ? 'Mismatch' : c.verdict === 'consistent' ? 'Consistent' : 'Unverified'}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    )}

    {review.cv_certifications && review.cv_certifications.length > 0 && (
      <Section title="Certificates mentioned in CV">
        <ul className="list-disc pl-5">
          {review.cv_certifications.map((c, i) => (
            <li key={i}>
              {c.name}
              {[c.issuer, c.year].filter(Boolean).length > 0 && (
                <span className="text-muted"> ({[c.issuer, c.year].filter(Boolean).join(', ')})</span>
              )}
            </li>
          ))}
        </ul>
      </Section>
    )}

    {review.documents && review.documents.length > 0 && (
      <Section title="Documents on file">
        <p>{review.documents.map((d) => d.original_filename).join(' · ')}</p>
      </Section>
    )}

    <SignOff />
  </>
);

const PanelBrief: React.FC<{ review: CandidateReviewDetail; marks: SkillMark[] }> = ({ review, marks }) => {
  const scored = marks.filter((m) => m.weight > 0);
  const strong = scored.filter((m) => m.level === 'same');
  const partial = scored.filter((m) => m.level === 'related');
  const missing = scored.filter((m) => m.level === 'none');
  const jobs = review.gov_experience?.jobs ?? [];
  const experience = review.evaluations.filter((e) => e.criterion_type === 'experience');
  const education = review.evaluations.filter((e) => e.criterion_type === 'education');
  const probes = probePoints(review, marks);

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 print:grid-cols-2 gap-5">
        <Section title="Work history">
          {jobs.length === 0 ? (
            <p className="text-muted">Not available.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {jobs.map((j, i) => (
                <li key={i}>
                  <span className="font-medium">{j.designation ?? 'Role not stated'}</span>, {j.organisation}
                  {j.period && <span className="text-muted"> · {j.period}</span>}
                  {j.is_government && j.role_relevant && <span className="text-primary font-semibold"> · Govt</span>}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Requirements">
          <ul className="flex flex-col gap-1">
            {[...experience, ...education].map((e) => (
              <li key={e.criterion_id} className="flex justify-between gap-3">
                <span>{e.criterion_description}</span>
                <span className="font-semibold whitespace-nowrap">
                  {RESULT_TEXT[e.result] ?? e.result}
                  {e.criterion_type === 'experience' && typeof e.match_percentage === 'number' ? ` (${e.match_percentage}%)` : ''}
                </span>
              </li>
            ))}
            {experience.length + education.length === 0 && <li className="text-muted">No experience or education criteria.</li>}
          </ul>
        </Section>
      </div>

      <Section title="Technical skills">
        <div className="grid grid-cols-1 sm:grid-cols-3 print:grid-cols-3 gap-4">
          <SkillColumn title={`Has (${strong.length})`} items={strong.map((m) => m.skill)} />
          <SkillColumn
            title={`Related only (${partial.length})`}
            items={partial.map((m) => `${m.skill} (has ${m.candidate_skill ?? 'related skill'})`)}
          />
          <SkillColumn title={`Missing (${missing.length})`} items={missing.map((m) => m.skill)} />
        </div>
      </Section>

      {review.cv_certifications && review.cv_certifications.length > 0 && (
        <Section title="Certificates">
          <p>{review.cv_certifications.map((c) => c.name).join(' · ')}</p>
        </Section>
      )}

      <Section title="Points to probe in the interview">
        {probes.length === 0 ? (
          <p className="text-muted">No gaps found in the screening.</p>
        ) : (
          <ol className="list-decimal pl-5 flex flex-col gap-1">
            {probes.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ol>
        )}
      </Section>

      <Section title="Panel notes">
        <div className="h-24 border border-border rounded-md" />
      </Section>
    </>
  );
};

const SkillColumn: React.FC<{ title: string; items: string[] }> = ({ title, items }) => (
  <div>
    <p className="text-xs font-semibold text-muted mb-1">{title}</p>
    {items.length === 0 ? (
      <p className="text-muted">—</p>
    ) : (
      <ul className="flex flex-col gap-0.5">
        {items.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    )}
  </div>
);

const SignOff: React.FC = () => (
  <section className="break-inside-avoid grid grid-cols-1 sm:grid-cols-3 print:grid-cols-3 gap-6 pt-8">
    {['Screened by', 'Verified by', 'Date'].map((label) => (
      <div key={label} className="border-t border-foreground/60 pt-1 text-xs text-muted">
        {label}
      </div>
    ))}
  </section>
);

export default CandidateReportPage;
