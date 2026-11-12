import React from 'react';
import { AlertTriangle, CheckCircle2, FileDown, Loader2 } from 'lucide-react';
import { useFetchResumes, useResumeFetchStatus } from '../hooks/useCandidates';
import { ApiError } from '../context/AuthContext';

/**
 * Roster-only profiles: resumes are downloaded from the roster's links, and
 * only for candidates the first (sheet-only) screening shortlisted. Failed
 * links can be retried.
 */
export const ResumeFetchPanel: React.FC<{ profileId?: string }> = ({ profileId }) => {
  const { data: status } = useResumeFetchStatus(profileId);
  const fetchResumes = useFetchResumes(profileId);

  if (!status) return null;
  const total = status.pending + status.fetching + status.fetched + status.failed + status.no_link;
  if (total === 0) return null;

  const running = status.fetching > 0 || fetchResumes.isPending;
  const error =
    fetchResumes.error instanceof ApiError ? fetchResumes.error.detail
    : null;

  return (
    <div className="bg-card border border-border rounded-lg p-5 shadow-sm flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <FileDown className="w-4.5 h-4.5 text-primary" />
        <h2 className="font-semibold text-base text-foreground">Resumes</h2>
      </div>
      <p className="text-sm text-muted font-normal leading-relaxed">
        Candidates are first screened from their roster row. Fetching downloads the resume only for
        eligible / needs-review candidates, then re-screens them with it. A candidate whose resume cannot be
        retrieved is moved to manual review.
      </p>

      <div className="flex flex-wrap gap-2 text-sm font-medium">
        <span className="px-2.5 py-1 bg-success/15 text-success rounded-md">{status.fetched} fetched</span>
        {status.fetching > 0 && (
          <span className="px-2.5 py-1 bg-warning/15 text-warning rounded-md">{status.fetching} fetching…</span>
        )}
        <span className="px-2.5 py-1 bg-muted/15 text-muted rounded-md">{status.pending} not fetched yet</span>
        {status.failed > 0 && (
          <span className="px-2.5 py-1 bg-danger/15 text-danger rounded-md">{status.failed} failed</span>
        )}
        {status.no_link > 0 && (
          <span className="px-2.5 py-1 bg-warning/15 text-warning rounded-md">{status.no_link} without a link</span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => fetchResumes.mutate({})}
          disabled={running || status.shortlisted_waiting === 0}
          className="bg-primary text-primary-foreground font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileDown className="w-4 h-4" />}
          {running ? 'Fetching resumes…' : `Fetch resumes for ${status.shortlisted_waiting} shortlisted`}
        </button>
        {status.failed > 0 && (
          <button
            onClick={() => fetchResumes.mutate({ retryFailed: true })}
            disabled={running}
            className="border border-border text-foreground font-semibold text-sm px-4 py-2.5 rounded-lg disabled:opacity-50"
          >
            Retry failed
          </button>
        )}
      </div>

      {error && (
        <div className="p-3 bg-danger/10 border border-danger/20 text-danger rounded-lg flex items-start gap-2 text-sm font-medium">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};

export default ResumeFetchPanel;
