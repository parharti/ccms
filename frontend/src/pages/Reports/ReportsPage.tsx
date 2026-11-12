import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Download, CheckCircle2, XCircle, HelpCircle, Clock, Users, Loader2, AlertCircle, Info } from 'lucide-react';
import { useResults } from '../../hooks/useResults';
import { useJobProfile } from '../../hooks/useJobProfile';
import { useScreeningRuns } from '../../hooks/useScreening';
import { StatusBadge } from '../../components/StatusBadge';
import { CertificatesCell } from '../../components/CertificationCells';
import { formatDateTime } from '../../lib/format';
import { BASE_URL } from '../../lib/api';

const FILTERS = [
  { value: undefined, label: 'All', icon: Users },
  { value: 'eligible', label: 'Eligible', icon: CheckCircle2 },
  { value: 'not_eligible', label: 'Not eligible', icon: XCircle },
  { value: 'needs_review', label: 'Needs review', icon: HelpCircle },
  { value: 'not_evaluated', label: 'Not screened yet', icon: Clock },
] as const;

const SUMMARY_CONFIG = [
  { key: 'total', label: 'Total', color: 'text-foreground', bg: 'bg-accent', border: 'border-border', icon: Users },
  { key: 'eligible', label: 'Eligible', color: 'text-success', bg: 'bg-success/10', border: 'border-success/20', icon: CheckCircle2 },
  { key: 'not_eligible', label: 'Not eligible', color: 'text-danger', bg: 'bg-danger/10', border: 'border-danger/20', icon: XCircle },
  { key: 'needs_review', label: 'Needs review', color: 'text-warning', bg: 'bg-warning/10', border: 'border-warning/20', icon: HelpCircle },
  { key: 'not_evaluated', label: 'Not screened yet', color: 'text-muted', bg: 'bg-muted/10', border: 'border-border', icon: Clock },
];

export const ReportsPage: React.FC = () => {
  const { profileId } = useParams<{ profileId: string }>();
  const { data: profile } = useJobProfile(profileId);
  const [status, setStatus] = useState<string | undefined>(undefined);
  // undefined = all screenings; otherwise only candidates from that run.
  const [runId, setRunId] = useState<string | undefined>(undefined);
  // null = follow the post's own "rank by suitability" setting; once HR
  // clicks the toggle it overrides that for this page view.
  const [rankedChoice, setRankedChoice] = useState<boolean | null>(null);
  const ranked = rankedChoice ?? profile?.rank_by_suitability ?? true;
  const setRanked = (value: boolean) => setRankedChoice(value);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const { data, isLoading } = useResults(profileId, status, runId, ranked);
  const { data: screeningRuns } = useScreeningRuns(profileId);

  // The export sends the SAME filters as the table query, so the sheet
  // contains exactly what the user is looking at.
  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      if (runId) params.set('run_id', runId);
      params.set('sort', ranked ? 'skill_match' : 'roster');
      const url = `${BASE_URL}/jd/profiles/${profileId}/results/export${params.toString() ? `?${params.toString()}` : ''}`;
      const response = await fetch(url, { credentials: 'include' });
      if (!response.ok) {
        setExportError('Could not download the report. Please try again.');
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objectUrl;
      const disposition = response.headers.get('content-disposition') || '';
      const match = disposition.match(/filename=(.+)/);
      a.download = match ? match[1] : 'results.xlsx';
      a.click();
      URL.revokeObjectURL(objectUrl);
    } catch {
      setExportError('Could not download the report. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <Link to={`/recruitment/${profileId}`} className="inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-primary transition-colors mb-3">
            <ArrowLeft className="w-4 h-4" /> Back to job profile
          </Link>
          <h1 className="font-bold text-2xl text-foreground">
            Results{profile ? <span className="font-normal text-muted"> — {profile.title}</span> : ''}
          </h1>
        </div>
        <div className="flex flex-col items-end gap-2">
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60 transition-opacity shadow-sm"
          >
            {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            {exporting ? 'Exporting…' : 'Export to Excel'}
          </button>
          {exportError && (
            <p className="flex items-center gap-1.5 text-sm font-semibold text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {exportError}
            </p>
          )}
        </div>
      </div>

      {/* Summary tiles */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {SUMMARY_CONFIG.map(({ key, label, color, bg, border, icon: Icon }) => (
            <div key={key} className={`${bg} border ${border} rounded-lg p-4 flex flex-col gap-2`}>
              <Icon className={`w-4 h-4 ${color}`} />
              <div>
                <p className={`text-2xl font-bold ${color}`}>{(data.summary as any)[key]}</p>
                <p className="text-sm font-medium text-foreground mt-0.5">{label}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Help box */}
      <div className="bg-accent/50 border border-border rounded-lg p-5 flex gap-3">
        <Info className="w-5 h-5 text-primary shrink-0 mt-0.5" />
        <div>
          <h2 className="text-base font-semibold text-foreground mb-2">What do these results mean?</h2>
          <ul className="flex flex-col gap-1.5 text-sm text-foreground font-normal">
            <li><span className="font-semibold text-success">Eligible</span> — meets every must-have criterion. Ranked by suitability: skills, experience and desirable items.</li>
            <li><span className="font-semibold text-warning">Needs manual review</span> — the system could not decide everything, or the candidate narrowly misses an experience must-have. “Strong candidate, with exception” marks near-misses with exceptional skills.</li>
            <li><span className="font-semibold text-danger">Not eligible</span> — fails at least one must-have criterion.</li>
            <li><span className="font-semibold text-muted">Not screened yet</span> — screening has not been run for this candidate.</li>
          </ul>
        </div>
      </div>

      {/* Filter tabs + screening-run filter + sort */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex gap-1.5 flex-wrap">
          {FILTERS.map((f) => {
            const isActive = status === f.value;
            return (
              <button
                key={f.label}
                onClick={() => setStatus(f.value)}
                className={`flex items-center gap-1.5 text-sm font-semibold px-5 py-2.5 rounded-lg border transition-all ${
                  isActive
                    ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                    : 'border-border text-foreground hover:border-primary/30 bg-card'
                }`}
              >
                <f.icon className="w-4 h-4" />
                {f.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setRanked(!ranked)}
            className={`text-sm font-semibold px-4 py-2.5 rounded-lg border transition-all ${
              ranked ? 'bg-primary text-primary-foreground border-primary shadow-sm' : 'border-border text-foreground hover:border-primary/30 bg-card'
            }`}
            title="Rank best first: eligible, then needs review (strong candidates with an exception on top), then not eligible; highest suitability score first within each"
          >
            {ranked ? 'Ranked by suitability' : 'Rank by suitability'}
          </button>
          {screeningRuns && screeningRuns.length > 0 && (
            <select
              value={runId ?? 'all'}
              onChange={(e) => setRunId(e.target.value === 'all' ? undefined : e.target.value)}
              className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-2.5 cursor-pointer"
              title="Show only candidates from one particular screening run — useful after changing criteria and re-screening"
            >
              <option value="all">All screenings</option>
              {screeningRuns.filter((r) => r.current_candidates !== 0).map((r) => {
                const n = r.current_candidates ?? r.total_candidates;
                return (
                  <option key={r.id} value={r.id}>
                    Screening of {formatDateTime(r.started_at)} ({n} candidate{n === 1 ? '' : 's'})
                  </option>
                );
              })}
            </select>
          )}
        </div>
      </div>

      {/* Results table */}
      <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
        {isLoading && (
          <div className="p-8 flex items-center justify-center gap-2 text-muted text-sm font-semibold">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading results…
          </div>
        )}
        {!isLoading && data?.candidates.length === 0 && (
          <div className="p-10 text-center flex flex-col items-center gap-2">
            <Users className="w-8 h-8 text-muted" />
            <p className="text-sm font-semibold text-foreground">No candidates match this filter</p>
            <p className="text-sm text-muted font-normal">Try a different status or screening filter above.</p>
          </div>
        )}
        {!isLoading && data && data.candidates.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-accent/60 border-b border-border">
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Candidate</th>
                  {ranked && <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">#</th>}
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Category</th>
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Suitability</th>
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Skills match</th>
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Certificates in CV</th>
                  <th className="text-left py-3 px-5 text-sm font-semibold text-foreground">Status</th>
                  <th className="py-3 px-5" />
                </tr>
              </thead>
              <tbody>
                {data.candidates.map((c, i) => (
                  <tr
                    key={c.id}
                    className={`border-b border-border/60 hover:bg-accent/40 transition-colors ${i % 2 === 0 ? '' : 'bg-accent/20'}`}
                  >
                    <td className="py-3 px-5 font-semibold text-foreground">{c.name || c.external_id}</td>
                    {ranked && <td className="py-3 px-5 text-muted font-semibold">{i + 1}</td>}
                    <td className="py-3 px-5 text-foreground font-normal">{c.normalized_category || c.raw_category || '—'}</td>
                    <td className="py-3 px-5 text-foreground font-semibold">{c.suitability_score != null ? `${c.suitability_score}` : '—'}</td>
                    <td className="py-3 px-5 text-foreground font-semibold">{c.skill_match_percentage != null ? `${c.skill_match_percentage}%` : '—'}</td>
                    <td className="py-3 px-5 align-top">
                      <CertificatesCell certifications={c.cv_certifications} screened={c.status !== 'not_evaluated'} />
                    </td>
                    <td className="py-3 px-5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <StatusBadge status={c.status} />
                        {c.gov_tag && <StatusBadge status="gov_tag" />}
                        {c.review_tag && (
                          <span title={c.review_note ?? undefined}><StatusBadge status={c.review_tag} /></span>
                        )}
                        {c.status_overridden && (
                          <span className="text-xs font-semibold text-warning bg-warning/10 border border-warning/20 rounded-md px-2 py-0.5">Overridden</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-5 text-right">
                      <Link
                        to={`/candidate/${profileId}/${c.id}`}
                        className="text-sm font-semibold text-primary hover:underline"
                      >
                        Review →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportsPage;
