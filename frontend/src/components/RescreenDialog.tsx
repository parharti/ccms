import React from 'react';
import { X, RotateCcw, Play, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { formatDateTime } from '../lib/format';
import { StatusBadge } from './StatusBadge';
import type { Candidate, ScreeningRun } from '../types';

interface Props {
  /** The candidates a re-screen would cover (all, or one screening's). */
  candidates: Candidate[];
  screeningRuns: ScreeningRun[];
  /** e.g. "the screening of 23 Oct 2026, 10:53" — omitted for everyone. */
  scopeLabel?: string;
  /** A stopped run that can be continued with the candidates it never reached. */
  resumableRun?: ScreeningRun;
  busy: boolean;
  onContinue: (runId: string) => void;
  onRescreenOutdated: () => void;
  onRescreenAll: () => void;
  onClose: () => void;
}

interface Group {
  key: string;
  label: string;
  run?: ScreeningRun;
  count: number;
  outdated: number;
}

/**
 * Asked before a re-screen: where the current results come from (one row
 * per screening session), whether the criteria changed since, and the
 * cheapest way forward — continue a stopped run, re-screen only outdated
 * results, or (after an explicit yes) re-screen everyone again.
 */
export const RescreenDialog: React.FC<Props> = ({
  candidates, screeningRuns, scopeLabel, resumableRun, busy,
  onContinue, onRescreenOutdated, onRescreenAll, onClose,
}) => {
  const runsById = new Map(screeningRuns.map((r) => [r.id, r]));
  const groups = new Map<string, Group>();
  for (const c of candidates) {
    const run = c.last_screening_run_id ? runsById.get(c.last_screening_run_id) : undefined;
    const key = c.results_outdated == null ? 'unscreened' : run ? run.id : 'untracked';
    const label =
      key === 'unscreened' ? 'Not screened yet'
      : run ? `Screening of ${formatDateTime(run.started_at)}`
      : 'Screened individually / before sessions were tracked';
    const g = groups.get(key) ?? { key, label, run, count: 0, outdated: 0 };
    g.count += 1;
    if (c.results_outdated) g.outdated += 1;
    groups.set(key, g);
  }
  // Newest session first; the two catch-all rows last.
  const rank = (g: Group) => (g.run ? -new Date(g.run.started_at).getTime() : g.key === 'untracked' ? 1 : 2);
  const rows = [...groups.values()].sort((a, b) => rank(a) - rank(b));

  const total = candidates.length;
  const outdated = candidates.filter((c) => c.results_outdated).length;
  const remaining = resumableRun?.remaining_candidates ?? 0;
  const nothingChanged = outdated === 0 && remaining === 0;

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-lg shadow-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="font-semibold text-base text-foreground flex items-center gap-2">
            <RotateCcw className="w-4.5 h-4.5 text-primary" />
            Re-screen {scopeLabel ? `candidates from ${scopeLabel}` : 'candidates'}
          </h2>
          <button onClick={onClose} className="text-muted hover:text-foreground p-1 rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5 flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <p className="text-sm font-semibold text-foreground">Where the current {total} results come from</p>
            <div className="border border-border rounded-lg overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-accent/50 text-muted">
                  <tr>
                    <th className="text-left font-semibold px-3 py-2">Session</th>
                    <th className="text-right font-semibold px-3 py-2">Candidates</th>
                    <th className="text-right font-semibold px-3 py-2">Outdated</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((g) => (
                    <tr key={g.key} className="border-t border-border">
                      <td className="px-3 py-2 text-foreground">
                        <div className="flex items-center gap-2 flex-wrap">
                          {g.label}
                          {g.run && g.run.status !== 'completed' && <StatusBadge status={g.run.status} />}
                        </div>
                        {g.run && g.run.status !== 'completed' && (
                          <p className="text-xs text-muted mt-0.5">
                            reached {g.run.processed_count} of {g.run.total_candidates} planned
                          </p>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-foreground">{g.count}</td>
                      <td className={`px-3 py-2 text-right font-semibold ${g.outdated ? 'text-warning' : 'text-muted'}`}>
                        {g.key === 'unscreened' ? '—' : g.outdated}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {remaining > 0 && resumableRun && (
            <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 flex flex-col gap-3">
              <p className="text-sm text-foreground">
                The re-screen of <span className="font-semibold">{formatDateTime(resumableRun.started_at)}</span> was
                stopped after {resumableRun.processed_count} of {resumableRun.total_candidates}.{' '}
                <span className="font-semibold">{remaining}</span> candidate{remaining === 1 ? ' was' : 's were'} never reached.
              </p>
              <button
                onClick={() => onContinue(resumableRun.id)}
                disabled={busy}
                className="self-start bg-primary text-primary-foreground font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50"
              >
                <Play className="w-4 h-4" /> Continue with the remaining {remaining}
              </button>
            </div>
          )}

          {outdated > 0 && (
            <div className="bg-warning/10 border border-warning/25 rounded-lg p-4 flex flex-col gap-3">
              <p className="text-sm text-foreground flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
                <span>
                  <span className="font-semibold">{outdated}</span> result{outdated === 1 ? ' was' : 's were'} produced
                  before the criteria were last edited, so {outdated === 1 ? 'it doesn’t' : 'they don’t'} reflect
                  the current criteria.
                </span>
              </p>
              <button
                onClick={onRescreenOutdated}
                disabled={busy}
                className={`self-start font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50 ${
                  remaining > 0
                    ? 'bg-card border border-border text-foreground hover:border-primary/40'
                    : 'bg-primary text-primary-foreground'
                }`}
              >
                <RotateCcw className="w-4 h-4" /> Re-screen only the {outdated} outdated
              </button>
            </div>
          )}

          {nothingChanged && (
            <div className="bg-success/10 border border-success/25 rounded-lg p-4 flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-success shrink-0 mt-0.5" />
              <p className="text-sm text-foreground">
                Nothing has changed since these results were produced — every result already reflects the current
                criteria. Re-screening uses one Gemini call per candidate. Do you still want to re-screen all {total}?
              </p>
            </div>
          )}

          <p className="text-xs text-muted">
            Changes to the experience tolerance, thresholds, suitability weights and skill weights are applied to
            existing results straight away, so they never need a re-screen.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border">
          <button
            onClick={onClose}
            className="bg-card border border-border text-foreground font-semibold text-sm px-5 py-2.5 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={onRescreenAll}
            disabled={busy || total === 0}
            className={`font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50 ${
              nothingChanged
                ? 'bg-primary text-primary-foreground'
                : 'bg-card border border-border text-foreground hover:border-primary/40'
            }`}
          >
            <RotateCcw className="w-4 h-4" />
            {nothingChanged ? `Yes, re-screen all ${total}` : `Re-screen all ${total}`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default RescreenDialog;
