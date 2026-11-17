import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ShieldCheck, User, Mail, Calendar, Tag, CheckCircle2, XCircle, HelpCircle, BookOpen, PlayCircle, Phone, Award, Landmark, Printer } from 'lucide-react';
import { useCandidateReview, useOverrideStatus } from '../../hooks/useReview';
import { useEvaluateCandidate } from '../../hooks/useScreening';
import { useJobProfile } from '../../hooks/useJobProfile';
import { StatusBadge } from '../../components/StatusBadge';
import { formatDateTime, formatDate } from '../../lib/format';
import { BASE_URL } from '../../lib/api';
import { formatSkillScore, skillScore } from '../../lib/skillScore';
import type { ReviewDocument, SkillMark } from '../../types';

const SKILL_LEVEL_LABEL: Record<SkillMark['level'], string> = {
  same: 'Same skill',
  related: 'Related skill',
  none: 'Not found',
};

const SKILL_LEVEL_TONE: Record<SkillMark['level'], string> = {
  same: 'text-success',
  related: 'text-warning',
  none: 'text-danger',
};

const SOURCE_LABEL: Record<string, string> = { sheet: 'Sheet', resume: 'Resume', both: 'Sheet + resume' };

// Per-skill marking: the JD skill, what the candidate has, the level
// (same 1 / related = HR's mark / none 0), HR's weight and the points it
// earned; the total is also shown as marks out of the post's skills weight.
const SkillMarksTable: React.FC<{ marks: SkillMark[]; sectionWeight?: number | null }> = ({ marks, sectionWeight }) => {
  const score = skillScore(marks, sectionWeight);
  return (
    <div className="pl-6 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left">
            <th className="py-2 pr-4 font-semibold text-foreground">JD skill</th>
            <th className="py-2 pr-4 font-semibold text-foreground">Candidate has</th>
            <th className="py-2 pr-4 font-semibold text-foreground">Match</th>
            <th className="py-2 pr-4 font-semibold text-foreground">Found in</th>
            <th className="py-2 pr-4 font-semibold text-foreground text-right">Mark × weight</th>
            <th className="py-2 font-semibold text-foreground text-right">Points</th>
          </tr>
        </thead>
        <tbody>
          {marks.map((m) => (
            <tr key={m.skill} className={`border-b border-border/60 align-top ${m.weight === 0 ? 'opacity-60' : ''}`}>
              <td className="py-2 pr-4 font-medium text-foreground">{m.skill}</td>
              <td className="py-2 pr-4 text-foreground">
                {m.candidate_skill || '—'}
                {m.reason && <p className="text-xs text-muted font-normal mt-0.5">{m.reason}</p>}
              </td>
              <td className={`py-2 pr-4 font-semibold whitespace-nowrap ${SKILL_LEVEL_TONE[m.level]}`}>{SKILL_LEVEL_LABEL[m.level]}</td>
              <td className="py-2 pr-4 text-muted whitespace-nowrap">{m.source ? SOURCE_LABEL[m.source] ?? m.source : '—'}</td>
              <td className="py-2 pr-4 text-right text-muted whitespace-nowrap">
                {m.weight === 0 ? 'not scored' : `${m.mark} × ${m.weight}`}
              </td>
              <td className="py-2 text-right font-semibold text-foreground">{m.weight === 0 ? '—' : m.points}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5} className="py-2 pr-4 text-right font-semibold text-foreground">Skills score</td>
            <td className="py-2 text-right font-bold text-foreground whitespace-nowrap">{score ? formatSkillScore(score) : '—'}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
};

// Gemini cites documents by the filename it saw in the page markers; match
// that citation back to an uploaded document leniently (exact name, then
// name without extension, then substring) so links survive small wording
// differences in the citation.
function findCitedDocument(citation: string | null | undefined, documents?: ReviewDocument[]): ReviewDocument | null {
  if (!citation || !documents?.length) return null;
  const cited = citation.trim().toLowerCase();
  const bare = cited.replace(/\.[^.]+$/, '');
  return (
    documents.find((d) => d.original_filename.toLowerCase() === cited) ||
    documents.find((d) => d.original_filename.toLowerCase().replace(/\.[^.]+$/, '') === bare) ||
    documents.find((d) => {
      const name = d.original_filename.toLowerCase();
      return name.includes(cited) || cited.includes(name.replace(/\.[^.]+$/, ''));
    }) ||
    null
  );
}

// A criterion's reasoning often mentions SEVERAL documents (e.g. an
// experience total summed across multiple certificates) while the citation
// field only holds one. Find every uploaded document whose filename appears
// in the reasoning text, so each can get its own link.
function findReferencedDocuments(text: string | null | undefined, documents?: ReviewDocument[]): ReviewDocument[] {
  if (!text || !documents?.length) return [];
  const t = text.toLowerCase();
  return documents.filter((d) => {
    const name = d.original_filename.toLowerCase();
    const bare = name.replace(/\.[^.]+$/, '');
    return t.includes(name) || (bare.length >= 4 && t.includes(bare));
  });
}

const OVERRIDE_OPTIONS = ['eligible', 'not_eligible', 'needs_review'] as const;

const RESULT_ICON: Record<string, React.ReactNode> = {
  pass: <CheckCircle2 className="w-4 h-4 text-success shrink-0 mt-0.5" />,
  fail: <XCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />,
  needs_review: <HelpCircle className="w-4 h-4 text-warning shrink-0 mt-0.5" />,
};

export const CandidatePage: React.FC = () => {
  const { profileId, candidateId } = useParams<{ profileId: string; candidateId: string }>();
  const { data: review, isLoading } = useCandidateReview(profileId, candidateId);
  const overrideStatus = useOverrideStatus(profileId, candidateId);
  const evaluateCandidate = useEvaluateCandidate(profileId);
  const { data: profile } = useJobProfile(profileId);

  const [overrideOpen, setOverrideOpen] = useState(false);
  const [newStatus, setNewStatus] = useState<(typeof OVERRIDE_OPTIONS)[number]>('eligible');
  const [reason, setReason] = useState('');
  const [screenError, setScreenError] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4 max-w-4xl">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-20 animate-pulse bg-border/40 rounded-lg" />
        ))}
      </div>
    );
  }
  if (!review) return <p className="text-sm font-semibold text-danger">Candidate not found.</p>;

  const handleOverride = async (e: React.FormEvent) => {
    e.preventDefault();
    await overrideStatus.mutateAsync({ new_status: newStatus, reason });
    setOverrideOpen(false);
    setReason('');
  };

  const handleScreen = async () => {
    if (!candidateId) return;
    setScreenError(null);
    try {
      await evaluateCandidate.mutateAsync(candidateId);
    } catch (err: any) {
      setScreenError(err?.detail || err?.message || 'Something went wrong. Please try again or contact IT support.');
    }
  };

  const passCount = review.evaluations.filter(e => e.result === 'pass').length;
  const failCount = review.evaluations.filter(e => e.result === 'fail').length;
  const reviewCount = review.evaluations.filter(e => e.result === 'needs_review').length;

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      {/* Back + header */}
      <div>
        <Link to={`/recruitment/${profileId}`} className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-primary transition-colors mb-3">
          <ArrowLeft className="w-4 h-4" /> Back to job profile
        </Link>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="font-bold text-2xl text-foreground">{review.name || 'Unnamed candidate'}</h1>
            <p className="text-sm text-foreground font-normal mt-1">
              {review.external_id && (
                <span className="font-semibold text-primary">ID: {review.external_id}</span>
              )}
              {review.external_id && review.email ? ' · ' : ''}
              {review.email || (review.external_id ? '' : '—')}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <StatusBadge status={review.status} className="text-sm px-3 py-1.5" />
            {review.gov_tag && <StatusBadge status="gov_tag" />}
            {review.review_tag && (
              <span title={review.review_note ?? undefined}><StatusBadge status={review.review_tag} /></span>
            )}
            {review.status_overridden && (
              <span className="text-xs font-semibold text-warning bg-warning/10 border border-warning/20 rounded-md px-2 py-0.5">
                Overridden · {formatDateTime(review.overridden_at)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 flex-wrap">
        {review.status !== 'not_evaluated' && (
          <>
            <Link
              to={`/candidate/${profileId}/${candidateId}/print/hr`}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold border border-border text-foreground hover:border-primary/40 transition-colors"
            >
              <Printer className="w-4 h-4 text-primary" /> HR report
            </Link>
            <Link
              to={`/candidate/${profileId}/${candidateId}/print/brief`}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold border border-border text-foreground hover:border-primary/40 transition-colors"
            >
              <Printer className="w-4 h-4 text-primary" /> Committee brief
            </Link>
          </>
        )}
        <button
          onClick={handleScreen}
          disabled={evaluateCandidate.isPending}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60 transition-opacity"
        >
          <PlayCircle className="w-4 h-4" />
          {evaluateCandidate.isPending ? 'Screening…' : 'Screen this candidate'}
        </button>
        <button
          onClick={() => setOverrideOpen(v => !v)}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all ${
            overrideOpen
              ? 'bg-accent border border-border text-foreground'
              : 'bg-card border border-border text-foreground hover:border-primary/40 hover:text-primary'
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          Override status
        </button>
      </div>

      {/* Screen error */}
      {screenError && (
        <div className="p-4 bg-danger/10 border border-danger/20 text-danger rounded-lg text-sm font-semibold">
          {screenError}
        </div>
      )}

      {/* Override panel */}
      {overrideOpen && (
        <form onSubmit={handleOverride} className="bg-accent/50 border border-border rounded-lg p-5 flex flex-col gap-4">
          <p className="text-base font-semibold text-foreground">Set new status</p>
          <div className="flex gap-2 flex-wrap">
            {OVERRIDE_OPTIONS.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => setNewStatus(opt)}
                className={`text-sm font-semibold px-5 py-2.5 rounded-lg border transition-all ${
                  newStatus === opt
                    ? opt === 'eligible' ? 'bg-success text-white border-success'
                    : opt === 'not_eligible' ? 'bg-danger text-white border-danger'
                    : 'bg-warning text-white border-warning'
                    : 'border-border text-foreground hover:border-primary/40'
                }`}
              >
                {opt.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for override (recommended — kept in the audit trail)…"
            className="bg-card border border-border text-foreground text-sm font-normal p-3 rounded-lg w-full min-h-[70px] focus:outline-none focus:border-primary transition-colors resize-none"
          />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setOverrideOpen(false)} className="text-sm font-semibold px-5 py-2.5 rounded-lg border border-border text-foreground hover:bg-accent transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={overrideStatus.isPending} className="text-sm font-semibold px-5 py-2.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-60 hover:opacity-90 transition-opacity">
              {overrideStatus.isPending ? 'Saving…' : 'Confirm override'}
            </button>
          </div>
        </form>
      )}

      {/* Candidate personal details */}
      <div className="bg-card border border-border rounded-lg p-6 shadow-sm">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <User className="w-4 h-4 text-primary" />
          </div>
          <h2 className="font-semibold text-base text-foreground">Candidate details</h2>
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4">
          {review.email && (
            <div>
              <dt className="text-sm font-medium text-muted flex items-center gap-1.5 mb-0.5">
                <Mail className="w-3.5 h-3.5" /> Email
              </dt>
              <dd className="text-sm font-medium text-foreground break-all">{review.email}</dd>
            </div>
          )}
          {review.phone && (
            <div>
              <dt className="text-sm font-medium text-muted flex items-center gap-1.5 mb-0.5">
                <Phone className="w-3.5 h-3.5" /> Phone
              </dt>
              <dd className="text-sm font-medium text-foreground">{review.phone}</dd>
            </div>
          )}
          {review.dob && (
            <div>
              <dt className="text-sm font-medium text-muted flex items-center gap-1.5 mb-0.5">
                <Calendar className="w-3.5 h-3.5" /> Date of birth
              </dt>
              <dd className="text-sm font-medium text-foreground">{formatDate(review.dob)}</dd>
            </div>
          )}
          {review.gender && (
            <div>
              <dt className="text-sm font-medium text-muted flex items-center gap-1.5 mb-0.5">
                <User className="w-3.5 h-3.5" /> Gender
              </dt>
              <dd className="text-sm font-medium text-foreground">{review.gender}</dd>
            </div>
          )}
          {review.normalized_category && (
            <div>
              <dt className="text-sm font-medium text-muted flex items-center gap-1.5 mb-0.5">
                <Tag className="w-3.5 h-3.5" /> Category
              </dt>
              <dd className="text-sm font-medium text-foreground">
                {review.normalized_category}
                {review.raw_category && review.raw_category !== review.normalized_category && (
                  <span className="text-muted font-normal"> ({review.raw_category})</span>
                )}
              </dd>
            </div>
          )}
          {review.ingestion_status && (
            <div>
              <dt className="text-sm font-medium text-muted mb-0.5">Documents</dt>
              <dd><StatusBadge status={review.ingestion_status} /></dd>
            </div>
          )}
          {review.computed_status && review.status_overridden && (
            <div>
              <dt className="text-sm font-medium text-muted mb-0.5">AI decision</dt>
              <dd><StatusBadge status={review.computed_status} /></dd>
            </div>
          )}
        </dl>
      </div>

      {/* Roster vs resume: experience + must-have items */}
      {review.resume_consistency && (
        <div className="bg-card border border-border rounded-lg p-6 shadow-sm">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
            <h2 className="font-semibold text-base text-foreground">Resume vs roster check</h2>
            <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${
              review.resume_consistency.overall === 'inconsistent'
                ? 'bg-destructive/10 border-destructive/20 text-destructive'
                : review.resume_consistency.overall === 'consistent'
                  ? 'bg-success/10 border-success/20 text-success'
                  : 'bg-accent/30 border-border text-muted'
            }`}>
              {review.resume_consistency.overall === 'inconsistent'
                ? 'Mismatch found'
                : review.resume_consistency.overall === 'consistent'
                  ? 'Consistent'
                  : 'Could not verify'}
            </span>
          </div>
          <ul className="flex flex-col gap-2">
            {review.resume_consistency.checks.map((c) => (
              <li key={c.item} className="border border-border bg-accent/30 rounded-lg px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-medium text-foreground">{c.item}</p>
                  <span className={`text-xs font-medium shrink-0 ${
                    c.verdict === 'inconsistent' ? 'text-destructive' : c.verdict === 'consistent' ? 'text-success' : 'text-muted'
                  }`}>{c.verdict}</span>
                </div>
                <p className="text-xs text-muted font-normal mt-1">
                  Roster: {c.roster ?? '—'} · Resume: {c.resume ?? '—'}
                </p>
                {c.note && <p className="text-xs text-muted font-normal mt-0.5">{c.note}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Government Relevant Experience: every job, and whether it counted */}
      {review.gov_experience && (
        <div className="bg-card border border-border rounded-lg p-6 shadow-sm">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <Landmark className="w-4 h-4 text-primary" />
              </div>
              <h2 className="font-semibold text-base text-foreground">Government relevant experience</h2>
            </div>
            <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${
              review.gov_tag ? 'bg-primary/10 border-primary/20 text-primary' : 'bg-accent/30 border-border text-muted'
            }`}>
              {review.gov_tag ? 'Tagged' : 'Not tagged'}
            </span>
          </div>
          <p className="text-xs text-muted font-normal mb-3">
            A job counts only when the employer is government / GovTech <em>and</em> the role is relevant to this post.
          </p>
          {review.gov_experience.jobs.length === 0 ? (
            <p className="text-sm text-muted font-normal">No jobs found in the sheet or resume.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {review.gov_experience.jobs.map((j, i) => {
                const counts = j.is_government && j.role_relevant;
                return (
                  <li key={i} className="border border-border bg-accent/30 rounded-lg px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-medium text-foreground">
                        {j.designation ? `${j.designation}, ` : ''}{j.organisation}
                        {j.period && <span className="text-muted font-normal"> · {j.period}</span>}
                      </p>
                      <span className={`text-xs font-medium shrink-0 ${counts ? 'text-primary' : 'text-muted'}`}>
                        {counts
                          ? 'Counts'
                          : j.is_government
                            ? 'Government, role not relevant'
                            : 'Not government'}
                      </span>
                    </div>
                    {j.reason && <p className="text-xs text-muted font-normal mt-1">{j.reason}</p>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}

      {/* Certifications listed in the CV */}
      {(() => {
        const certs = review.cv_certifications;
        const screened = review.status !== 'not_evaluated';
        return (
          <div className="bg-card border border-border rounded-lg p-6 shadow-sm">
            <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                  <Award className="w-4 h-4 text-primary" />
                </div>
                <h2 className="font-semibold text-base text-foreground">Certificates mentioned in CV</h2>
              </div>
            </div>
            {certs == null ? (
              <p className="text-sm text-muted font-normal">
                {screened
                  ? 'No readable CV/resume was found for this candidate, so no certificates could be extracted.'
                  : 'Certificates are extracted from the CV when the candidate is screened.'}
              </p>
            ) : certs.length === 0 ? (
              <p className="text-sm text-muted font-normal">The CV does not mention any certificates.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {certs.map((c) => (
                  <li key={c.name} className={`border rounded-lg px-4 py-3 flex items-start justify-between gap-3 border-border bg-accent/30`}>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground">{c.name}</p>
                      {(c.issuer || c.year) && (
                        <p className="text-xs text-muted font-normal mt-0.5">{[c.issuer, c.year].filter(Boolean).join(' · ')}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })()}

      {/* Evaluation summary bar */}
      {review.evaluations.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-success/10 border border-success/20 rounded-lg p-4 flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
            <div>
              <p className="text-2xl font-bold text-success">{passCount}</p>
              <p className="text-sm font-medium text-foreground">Passed</p>
            </div>
          </div>
          <div className="bg-danger/10 border border-danger/20 rounded-lg p-4 flex items-center gap-3">
            <XCircle className="w-5 h-5 text-danger shrink-0" />
            <div>
              <p className="text-2xl font-bold text-danger">{failCount}</p>
              <p className="text-sm font-medium text-foreground">Failed</p>
            </div>
          </div>
          <div className="bg-warning/10 border border-warning/20 rounded-lg p-4 flex items-center gap-3">
            <HelpCircle className="w-5 h-5 text-warning shrink-0" />
            <div>
              <p className="text-2xl font-bold text-warning">{reviewCount}</p>
              <p className="text-sm font-medium text-foreground">Needs review</p>
            </div>
          </div>
        </div>
      )}

      {/* Criterion evaluations */}
      <div className="bg-card border border-border rounded-lg p-6 shadow-sm flex flex-col gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <BookOpen className="w-4 h-4 text-primary" />
          </div>
          <h2 className="font-semibold text-base text-foreground">Criterion evaluations</h2>
        </div>

        {review.evaluations.length === 0 ? (
          <div className="py-8 text-center flex flex-col items-center gap-2">
            <div className="w-10 h-10 rounded-lg bg-accent border border-border flex items-center justify-center">
              <BookOpen className="w-5 h-5 text-muted" />
            </div>
            <p className="text-sm font-semibold text-foreground">Not screened yet</p>
            <p className="text-sm text-muted font-normal">Run screening from the job profile page to evaluate this candidate.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {review.evaluations.map((ev) => (
              <div
                key={ev.criterion_id}
                className={`border rounded-lg p-4 flex flex-col gap-2 transition-colors ${
                  ev.result === 'pass' ? 'border-success/20 bg-success/5'
                  : ev.result === 'fail' ? 'border-danger/20 bg-danger/5'
                  : 'border-warning/20 bg-warning/5'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2 min-w-0">
                    {RESULT_ICON[ev.result] ?? RESULT_ICON['needs_review']}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                        <span className="text-xs font-semibold px-2 py-0.5 bg-primary/10 text-primary rounded-md">{ev.criterion_type}</span>
                        {ev.is_essential && (
                          <span className="text-xs font-semibold px-2 py-0.5 bg-danger/10 text-danger rounded-md">Must-have</span>
                        )}
                      </div>
                      <p className="text-sm font-medium text-foreground">{ev.criterion_description}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {typeof ev.match_percentage === 'number' && ev.criterion_type === 'skill' && (
                      <span
                        className={`text-sm font-semibold px-3 py-1 rounded-md border ${
                          ev.match_percentage >= 70
                            ? 'bg-success/10 text-success border-success/20'
                            : ev.match_percentage >= 40
                            ? 'bg-warning/10 text-warning border-warning/20'
                            : 'bg-danger/10 text-danger border-danger/20'
                        }`}
                      >
                        Skills &amp; experience match: {ev.match_percentage}%
                      </span>
                    )}
                    {typeof ev.match_percentage === 'number' && ev.criterion_type !== 'skill' && (
                      <span
                        className={`text-sm font-semibold px-3 py-1 rounded-md border ${
                          ev.match_percentage >= 100
                            ? 'bg-success/10 text-success border-success/20'
                            : 'bg-danger/10 text-danger border-danger/20'
                        }`}
                      >
                        Required experience: {ev.match_percentage}%
                      </span>
                    )}
                    {(ev.criterion_type !== 'skill' || ev.is_essential) && <StatusBadge status={ev.result} />}
                  </div>
                </div>
                {ev.skill_marks && ev.skill_marks.length > 0 && <SkillMarksTable marks={ev.skill_marks} sectionWeight={profile?.weight_skills} />}
                {ev.reasoning && (
                  <p className="text-sm text-foreground font-normal leading-relaxed pl-6">{ev.reasoning}</p>
                )}
                {(() => {
                  const docFileUrl = (docId: string) =>
                    `${BASE_URL}/jd/profiles/${profileId}/candidates/${candidateId}/documents/${docId}/file`;
                  const citedDoc = findCitedDocument(ev.citation_document, review.documents);
                  const alsoReferenced = findReferencedDocuments(ev.reasoning, review.documents)
                    .filter((d) => d.id !== citedDoc?.id);
                  return (
                    <>
                      {(ev.citation_document || ev.citation_page) && (
                        <p className="text-sm font-medium text-primary pl-6">
                          Source:{' '}
                          {citedDoc ? (
                            <a
                              href={docFileUrl(citedDoc.id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="underline underline-offset-2 hover:text-primary/70"
                              title="Open this document in a new tab"
                            >
                              {ev.citation_document || citedDoc.original_filename}
                            </a>
                          ) : (
                            ev.citation_document || 'document'
                          )}
                          {ev.citation_page ? `, page ${ev.citation_page}` : ''}
                        </p>
                      )}
                      {alsoReferenced.length > 0 && (
                        <p className="text-sm font-medium text-primary pl-6 flex flex-wrap items-center gap-x-3 gap-y-1">
                          <span className="text-muted font-normal">Documents mentioned in reasoning:</span>
                          {alsoReferenced.map((d) => (
                            <a
                              key={d.id}
                              href={docFileUrl(d.id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="underline underline-offset-2 hover:text-primary/70"
                              title="Open this document in a new tab"
                            >
                              {d.original_filename}
                            </a>
                          ))}
                        </p>
                      )}
                    </>
                  );
                })()}
                {ev.criterion_type === 'skill' && typeof ev.match_percentage === 'number' && !ev.is_essential && (
                  <p className="text-xs text-muted font-normal pl-6">
                    This score is for information only — it does not affect eligibility.
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default CandidatePage;
