import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Edit2, Trash2, Plus, Save, BarChart3, Users, RotateCcw, Play,
  ArrowRight, ArrowLeft, Check, UploadCloud, Loader2, AlertTriangle, Search, Square,
} from 'lucide-react';
import { useJobProfile, useAddCriterion, useUpdateCriterion, useDeleteCriterion } from '../../hooks/useJobProfile';
import { useDeleteProfile } from '../../hooks/useJobProfiles';
import { useCandidates, useResetCandidates } from '../../hooks/useCandidates';
import {
  useStartScreening, useStopScreening, useContinueScreening, useScreeningRun, useScreeningRuns,
} from '../../hooks/useScreening';
import { useQueryClient } from '@tanstack/react-query';
import { formatDateTime } from '../../lib/format';
import { StatusBadge } from '../../components/StatusBadge';
import { CertificatesCell } from '../../components/CertificationCells';
import { CandidateUploadPanel } from '../../components/CandidateUploadPanel';
import { ResumeFetchPanel } from '../../components/ResumeFetchPanel';
import { ScreeningSettingsCard } from '../../components/ScreeningSettingsCard';
import { AddCandidateModal } from '../../components/AddCandidateModal';
import { SkillItemsEditor } from '../../components/SkillItemsEditor';
import { RescreenDialog } from '../../components/RescreenDialog';
import { rankCandidates, resultGroup } from '../../lib/ranking';
import type { Criterion, SkillItem } from '../../types';

const CRITERION_TYPES = ['age', 'education', 'experience', 'skill', 'other'];

type Step = 1 | 2 | 3;

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: 'JD criteria' },
  { n: 2, label: 'Upload candidates' },
  { n: 3, label: 'Results' },
];

const STEP_INSTRUCTIONS: Record<Step, string> = {
  1: 'Check the criteria below. Edit anything that looks wrong, then press Confirm criteria.',
  2: 'Upload the two files below, then press Upload & Start Screening.',
  3: 'Results for every candidate are listed below.',
};

export const ProfileDetailPage: React.FC = () => {
  const { profileId } = useParams<{ profileId: string }>();
  const { data: profile, isLoading } = useJobProfile(profileId);
  const { data: candidates, isLoading: candidatesLoading } = useCandidates(profileId);
  const addCriterion = useAddCriterion(profileId);
  const updateCriterion = useUpdateCriterion(profileId);
  const deleteCriterion = useDeleteCriterion(profileId);
  const startScreening = useStartScreening(profileId);
  const resetCandidates = useResetCandidates(profileId);
  const deleteProfile = useDeleteProfile();
  const navigate = useNavigate();

  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [screeningError, setScreeningError] = useState<string | null>(null);
  const { data: run } = useScreeningRun(profileId, runId);
  const stopScreening = useStopScreening(profileId);
  const continueScreening = useContinueScreening(profileId);
  // "stopping" = Stop pressed, in-flight candidates still finishing.
  const runActive = run?.status === 'running' || run?.status === 'stopping';
  const { data: screeningRuns } = useScreeningRuns(profileId);

  // Wizard step. Until the user navigates manually, the step is derived
  // from the data: a profile that already has candidates goes STRAIGHT to
  // Results; a fresh JD starts at the criteria review step.
  const [stepOverride, setStepOverride] = useState<Step | null>(null);
  const hasCandidates = (candidates?.length ?? 0) > 0;
  const step: Step = stepOverride ?? (hasCandidates ? 3 : 1);

  // Re-screen dialog: null = closed; runId scopes it to one screening.
  const [rescreenScope, setRescreenScope] = useState<{ runId?: string } | null>(null);
  const outdatedCount = (candidates ?? []).filter((c) => c.results_outdated).length;
  // Results produced under since-edited criteria: ask once, as Results
  // opens, whether to re-screen them (asked again after a later edit).
  const outdatedPrompted = useRef(false);
  useEffect(() => {
    if (outdatedCount === 0) {
      outdatedPrompted.current = false;
    } else if (step === 3 && !runActive && !outdatedPrompted.current) {
      outdatedPrompted.current = true;
      setRescreenScope({});
    }
  }, [outdatedCount, step, runActive]);

  // When a screening run finishes, refresh the candidates table and
  // dashboard so status badges update automatically without a page reload.
  useEffect(() => {
    if (run?.status === 'completed' || run?.status === 'stopped' || run?.status === 'failed') {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] });
      queryClient.invalidateQueries({ queryKey: ['screening-runs', profileId] });
    }
  }, [run?.status, profileId, queryClient]);

  // While screening runs, refresh the candidates table on every progress
  // tick so results stream into the table live instead of appearing only
  // at the very end.
  useEffect(() => {
    if (runActive && run && run.processed_count > 0) {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
    }
  }, [run?.processed_count, run?.status, profileId, queryClient]);

  // Upload phase tracking -- the wizard switches to the Results screen the
  // moment "Upload & Start Screening" is clicked, so the user watches one
  // status component go: uploading -> screening -> results.
  const [uploadPhase, setUploadPhase] = useState<'idle' | 'uploading' | 'error'>('idle');
  const [uploadPhaseError, setUploadPhaseError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<Criterion>>({});
  const [addingNew, setAddingNew] = useState(false);
  const [newCriterion, setNewCriterion] = useState<{
    type: string;
    description: string;
    is_essential: boolean;
    required_match_percentage: number | null;
    skill_items: SkillItem[];
    related_mark: number | null;
  }>({
    type: 'other',
    description: '',
    is_essential: true,
    required_match_percentage: null,
    skill_items: [],
    related_mark: null,
  });

  // Client-side search over the candidates table (step 3).
  const [candidateSearch, setCandidateSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [resumeFilter, setResumeFilter] = useState('all');
  // null = follow the post's "rank by suitability" setting; the dropdown overrides it here.
  const [orderChoice, setOrderChoice] = useState<'ranked' | 'roster' | null>(null);
  // "all" or a screening-run id — show only candidates from that run.
  const [runFilter, setRunFilter] = useState('all');
  const [addCandidateOpen, setAddCandidateOpen] = useState(false);

  if (isLoading || candidatesLoading) return <p className="text-sm font-medium text-muted">Loading job profile…</p>;
  if (!profile) return <p className="text-sm font-medium text-danger">Job profile not found.</p>;

  const startEdit = (c: Criterion) => {
    setEditingId(c.id);
    setDraft({
      type: c.type,
      description: c.description,
      is_essential: c.is_essential,
      required_match_percentage: c.required_match_percentage ?? null,
      skill_items: c.skill_items ?? [],
      related_mark: c.related_mark ?? null,
    });
  };

  const saveEdit = async (criterionId: string) => {
    // An emptied skill list is sent as null, so the backend re-splits the description.
    const payload = draft.type === 'skill' && !draft.skill_items?.length ? { ...draft, skill_items: null } : draft;
    await updateCriterion.mutateAsync({ criterionId, payload });
    setEditingId(null);
  };

  const handleAddCriterion = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCriterion.description.trim()) return;
    await addCriterion.mutateAsync(newCriterion);
    setNewCriterion({
      type: 'other',
      description: '',
      is_essential: true,
      required_match_percentage: null,
      skill_items: [],
      related_mark: null,
    });
    setAddingNew(false);
  };

  const handleStartScreening = async (force = false, scopeRunId?: string, outdated = false) => {
    setScreeningError(null);
    setRunId(null);
    setRescreenScope(null);
    try {
      const result = await startScreening.mutateAsync({ force, runId: scopeRunId, outdated });
      setRunId(result.id);
      // A scoped re-screen moves its candidates into the NEW run, so the
      // old-run filter would show an emptying table — reset to all.
      if (scopeRunId) setRunFilter('all');
      queryClient.invalidateQueries({ queryKey: ['screening-runs', profileId] });
    } catch (err: any) {
      setScreeningError(err?.detail || err?.message || 'Something went wrong while starting screening. Please try again, or contact IT support if it keeps happening.');
    }
  };

  // Step 2's single action, in three beats: the moment upload starts we
  // jump to Results with an "uploading" banner; when the upload lands we
  // kick off screening (live progress bar); results stream in below.
  const handleContinueScreening = async (stoppedRunId: string) => {
    setScreeningError(null);
    setRescreenScope(null);
    try {
      const result = await continueScreening.mutateAsync(stoppedRunId);
      setRunId(result.id);
    } catch (err: any) {
      setScreeningError(err?.detail || err?.message || 'Could not continue the screening. Please try again.');
    }
  };

  const handleUploadStart = () => {
    setUploadPhaseError(null);
    setScreeningError(null);
    setRunId(null);
    setUploadPhase('uploading');
    setStepOverride(3);
  };

  const handleUploadedAndScreen = async () => {
    setUploadPhase('idle');
    await handleStartScreening(false);
  };

  const handleUploadError = (message: string) => {
    setUploadPhase('error');
    setUploadPhaseError(message);
  };

  const statusCounts = (candidates ?? []).reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});

  const searchTerm = candidateSearch.trim().toLowerCase();
  // The screening-run filter also scopes the Re-screen / Delete actions,
  // so it's computed separately from the status/search table filters.
  const runScopedCandidates = (candidates ?? []).filter(
    (c) => runFilter === 'all' || c.last_screening_run_id === runFilter
  );
  const selectedRun = runFilter === 'all' ? undefined : screeningRuns?.find((r) => r.id === runFilter);
  // A stopped run that can pick up where it left off (this session's run
  // first, else the newest one in the history).
  const resumableRun = [run, ...(screeningRuns ?? [])].find((r) => r?.remaining_candidates) ?? undefined;
  // The table's filter dropdowns count within the selected screening, so
  // their numbers match what picking that option actually shows.
  const scopedStatusCounts = runScopedCandidates.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});
  const resumeCounts = runScopedCandidates.reduce<Record<string, number>>((acc, c) => {
    if (c.resume_fetch_status) acc[c.resume_fetch_status] = (acc[c.resume_fetch_status] ?? 0) + 1;
    return acc;
  }, {});
  const ranked = (orderChoice ?? (profile?.rank_by_suitability === false ? 'roster' : 'ranked')) === 'ranked';
  // Ranked: best first, same ordering as the Reports page / Excel export
  // (see lib/ranking). Roster order (the backend's) keeps the original Excel rows.
  const rankedCandidates = ranked ? rankCandidates(runScopedCandidates) : runScopedCandidates;
  const filteredCandidates = rankedCandidates
    .filter((c) => statusFilter === 'all' || c.status === statusFilter)
    .filter((c) => resumeFilter === 'all' || c.resume_fetch_status === resumeFilter)
    .filter(
      (c) =>
        !searchTerm ||
        (c.name ?? '').toLowerCase().includes(searchTerm) ||
        (c.external_id ?? '').toLowerCase().includes(searchTerm) ||
        (c.email ?? '').toLowerCase().includes(searchTerm)
    );

  const isStepReachable = (n: Step) =>
    n === 3 ? hasCandidates || !!runId || uploadPhase !== 'idle' || step === 3 : true;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="font-bold text-2xl text-foreground">{profile.title}</h1>
          <p className="text-sm text-foreground font-normal mt-1">
            {profile.method_of_recruitment || 'Job profile'}
            {profile.pay_scale ? ` · ${profile.pay_scale}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/reports/${profile.id}`}
            className="bg-card border border-border font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 text-foreground hover:border-primary/40"
          >
            <BarChart3 className="w-4 h-4 text-primary" />
            Full report
          </Link>
          <button
            onClick={async () => {
              if (
                window.confirm(
                  `Delete "${profile.title}"?\n\nThis permanently removes the JD profile along with ALL its candidates, documents and screening results. This cannot be undone.`
                )
              ) {
                await deleteProfile.mutateAsync(profile.id);
                navigate('/recruitment');
              }
            }}
            disabled={deleteProfile.isPending}
            className="bg-card border border-border font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 text-danger hover:border-danger/40 disabled:opacity-50"
            title="Delete this JD and all its data"
          >
            <Trash2 className="w-4 h-4" />
            {deleteProfile.isPending ? 'Deleting…' : 'Delete JD'}
          </button>
        </div>
      </div>

      {/* Step indicator */}
      <div className="bg-card border border-border rounded-lg p-4 shadow-sm">
        <div className="flex items-center">
          {STEPS.map(({ n, label }, i) => {
            const isActive = step === n;
            const isDone = step > n;
            const reachable = isStepReachable(n);
            return (
              <React.Fragment key={n}>
                {i > 0 && <div className={`flex-1 h-0.5 mx-2 rounded-full ${step > i ? 'bg-primary' : 'bg-border'}`} />}
                <button
                  onClick={() => reachable && setStepOverride(n)}
                  disabled={!reachable}
                  className={`flex items-center gap-2.5 px-4 py-2.5 rounded-lg transition-colors ${
                    isActive ? 'bg-primary/10' : reachable ? 'hover:bg-accent' : 'opacity-40 cursor-not-allowed'
                  }`}
                >
                  <span
                    className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border ${
                      isActive
                        ? 'bg-primary text-primary-foreground border-primary'
                        : isDone
                        ? 'bg-success/10 text-success border-success/30'
                        : 'bg-accent text-muted border-border'
                    }`}
                  >
                    {isDone ? <Check className="w-4 h-4" /> : n}
                  </span>
                  <span className="text-left">
                    <span className={`block text-xs font-medium ${isActive ? 'text-primary' : 'text-muted'}`}>
                      Step {n}
                    </span>
                    <span className={`block text-sm font-semibold ${isActive ? 'text-foreground' : 'text-muted'}`}>{label}</span>
                  </span>
                </button>
              </React.Fragment>
            );
          })}
        </div>
        <p className="text-sm font-normal text-foreground mt-3 pt-3 border-t border-border">
          {STEP_INSTRUCTIONS[step]}
        </p>
      </div>

      {/* ---------------- STEP 1: JD CRITERIA ---------------- */}
      {step === 1 && profile && <ScreeningSettingsCard profile={profile} />}

      {step === 1 && (
        <div className="bg-card border border-border rounded-lg p-4 sm:p-6 shadow-sm flex flex-col gap-4 max-w-4xl">
          <div className="flex items-center flex-wrap justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Edit2 className="w-4.5 h-4.5 text-primary" />
                <h2 className="font-semibold text-base text-foreground">Review JD criteria</h2>
              </div>
              <p className="text-sm text-muted font-normal mt-1">
                These were auto-extracted from the JD. Edit, add or remove anything, then confirm to continue.
              </p>
            </div>
            <button
              onClick={() => setAddingNew((v) => !v)}
              className="text-sm font-semibold text-primary flex items-center gap-1.5 px-5 py-2.5 rounded-lg border border-border hover:border-primary/40 shrink-0"
            >
              <Plus className="w-4 h-4" /> Add criterion
            </button>
          </div>

          {profile.base_age_min != null && (
            <div className="text-sm font-medium text-foreground bg-accent/50 rounded-lg px-3 py-2">
              Base age range: {profile.base_age_min}–{profile.base_age_max}
              {profile.age_relaxation_rules.length > 0 &&
                ` · ${profile.age_relaxation_rules.length} category relaxation rule(s) apply automatically`}
            </div>
          )}

          {addingNew && (
            <form onSubmit={handleAddCriterion} className="flex flex-col gap-3 bg-accent/40 rounded-lg p-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <select
                  value={newCriterion.type}
                  onChange={(e) =>
                    setNewCriterion((c) => ({
                      ...c,
                      type: e.target.value,
                      // Skills are informational by default — they only gate
                      // eligibility if HR deliberately makes them essential.
                      is_essential: e.target.value === 'skill' ? false : c.is_essential,
                    }))
                  }
                  className="bg-card border border-border text-foreground text-sm font-medium p-2.5 rounded-lg"
                >
                  {CRITERION_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <input
                    type="checkbox"
                    checked={newCriterion.is_essential}
                    onChange={(e) => setNewCriterion((c) => ({ ...c, is_essential: e.target.checked }))}
                  />
                  Must-have
                </label>
              </div>
              {newCriterion.type === 'skill' && newCriterion.is_essential && (
                <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                  Minimum match % to qualify:
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={newCriterion.required_match_percentage ?? ''}
                    onChange={(e) =>
                      setNewCriterion((c) => ({
                        ...c,
                        required_match_percentage: e.target.value === '' ? null : Number(e.target.value),
                      }))
                    }
                    placeholder="e.g. 60"
                    className="bg-card border border-border text-foreground text-sm font-medium p-2 rounded-lg w-24"
                  />
                  <span className="text-sm text-muted font-normal">
                    Candidates below this score will be marked not eligible.
                  </span>
                </label>
              )}
              <textarea
                value={newCriterion.description}
                onChange={(e) => setNewCriterion((c) => ({ ...c, description: e.target.value }))}
                placeholder="Describe the criterion…"
                required
                className="bg-card border border-border text-foreground text-sm font-normal p-3 rounded-lg w-full min-h-[60px]"
              />
              {newCriterion.type === 'skill' && (
                <SkillItemsEditor
                  items={newCriterion.skill_items}
                  onChange={(skill_items) => setNewCriterion((c) => ({ ...c, skill_items }))}
                  relatedMark={newCriterion.related_mark}
                  onRelatedMarkChange={(related_mark) => setNewCriterion((c) => ({ ...c, related_mark }))}
                  editableNames
                />
              )}
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => setAddingNew(false)}
                  className="text-sm font-semibold px-5 py-2.5 rounded-lg border border-border text-foreground"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={addCriterion.isPending}
                  className="text-sm font-semibold px-5 py-2.5 rounded-lg bg-primary text-primary-foreground"
                >
                  Save criterion
                </button>
              </div>
            </form>
          )}

          <div className="flex flex-col gap-2">
            {profile.criteria
              .slice()
              .sort((a, b) => a.display_order - b.display_order)
              .map((c) => (
                <div key={c.id} className="border border-border rounded-lg p-4">
                  {editingId === c.id ? (
                    <div className="flex flex-col gap-2">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <select
                          value={draft.type}
                          onChange={(e) => setDraft((d) => ({ ...d, type: e.target.value }))}
                          className="bg-accent/40 border border-border text-foreground text-sm font-medium p-2 rounded-lg"
                        >
                          {CRITERION_TYPES.map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                          <input
                            type="checkbox"
                            checked={!!draft.is_essential}
                            onChange={(e) => setDraft((d) => ({ ...d, is_essential: e.target.checked }))}
                          />
                          Must-have
                        </label>
                      </div>
                      {draft.type === 'skill' && draft.is_essential && (
                        <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                          Minimum match % to qualify:
                          <input
                            type="number"
                            min={1}
                            max={100}
                            value={draft.required_match_percentage ?? ''}
                            onChange={(e) =>
                              setDraft((d) => ({
                                ...d,
                                required_match_percentage: e.target.value === '' ? null : Number(e.target.value),
                              }))
                            }
                            placeholder="e.g. 60"
                            className="bg-card border border-border text-foreground text-sm font-medium p-2 rounded-lg w-24"
                          />
                          <span className="text-sm text-muted font-normal">
                            Candidates below this score will be marked not eligible.
                          </span>
                        </label>
                      )}
                      <textarea
                        value={draft.description}
                        onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                        className="bg-accent/40 border border-border text-foreground text-sm font-normal p-2.5 rounded-lg w-full min-h-[50px]"
                      />
                      {draft.type === 'skill' && (
                        <SkillItemsEditor
                          items={draft.skill_items ?? []}
                          onChange={(skill_items) => setDraft((d) => ({ ...d, skill_items }))}
                          relatedMark={draft.related_mark}
                          onRelatedMarkChange={(related_mark) => setDraft((d) => ({ ...d, related_mark }))}
                          editableNames
                        />
                      )}
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => setEditingId(null)}
                          className="text-sm font-semibold px-5 py-2.5 rounded-lg border border-border text-foreground"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={() => saveEdit(c.id)}
                          className="text-sm font-semibold px-5 py-2.5 rounded-lg bg-primary text-primary-foreground flex items-center gap-1.5"
                        >
                          <Save className="w-4 h-4" /> Save
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start flex-wrap justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium px-2 py-0.5 bg-primary/10 text-primary rounded-md">
                            {c.type}
                          </span>
                          {c.is_essential && (
                            <span className="text-xs font-medium px-2 py-0.5 bg-danger/10 text-danger rounded-md">
                              Must-have
                            </span>
                          )}
                          {c.type === 'skill' && c.is_essential && c.required_match_percentage != null && (
                            <span className="text-xs font-medium px-2 py-0.5 bg-warning/10 text-warning rounded-md">
                              Minimum {c.required_match_percentage}% match required
                            </span>
                          )}
                          {c.type === 'skill' && !(c.is_essential && c.required_match_percentage != null) && (
                            <span className="text-xs font-medium px-2 py-0.5 bg-accent text-foreground rounded-md">
                              Information only
                            </span>
                          )}
                        </div>
                        <p className="text-sm font-normal text-foreground">{c.description}</p>
                        {c.type === 'skill' && c.skill_items && (
                          <div className="mt-3">
                            <SkillItemsEditor
                              items={c.skill_items}
                              disabled={updateCriterion.isPending}
                              onChange={(skill_items) =>
                                updateCriterion.mutate({ criterionId: c.id, payload: { skill_items } })
                              }
                              relatedMark={c.related_mark}
                              onRelatedMarkChange={(related_mark) =>
                                updateCriterion.mutate({ criterionId: c.id, payload: { related_mark } })
                              }
                            />
                          </div>
                        )}
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <button
                          onClick={() => startEdit(c)}
                          className="text-sm font-semibold px-5 py-2.5 rounded-lg border border-border text-foreground flex items-center gap-1.5"
                          title="Edit criterion"
                        >
                          <Edit2 className="w-4 h-4 text-muted" />
                          Edit
                        </button>
                        <button
                          onClick={async () => {
                            if (!confirm(`Delete this criterion?\n\n"${c.description}"\n\nIts results will disappear from past screening breakdowns; candidates keep their current status until re-screened.`)) return;
                            try {
                              await deleteCriterion.mutateAsync(c.id);
                            } catch (err: any) {
                              alert(`Could not delete criterion: ${err?.detail || err?.message || 'Unknown error'}`);
                            }
                          }}
                          disabled={deleteCriterion.isPending}
                          className="text-sm font-semibold px-5 py-2.5 rounded-lg border border-border text-danger flex items-center gap-1.5 disabled:opacity-50"
                          title="Delete criterion"
                        >
                          <Trash2 className="w-4 h-4" />
                          {deleteCriterion.isPending ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            {profile.criteria.length === 0 && (
              <p className="text-sm text-muted font-normal">No criteria yet — add one above.</p>
            )}
          </div>

          <div className="flex justify-end pt-2 border-t border-border">
            <button
              onClick={() => setStepOverride(2)}
              disabled={profile.criteria.length === 0}
              className="bg-primary text-primary-foreground font-semibold text-sm px-4 sm:px-6 py-3 rounded-lg flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Confirm criteria
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* ---------------- STEP 2: UPLOAD CANDIDATES ---------------- */}
      {step === 2 && (
        <div className="flex flex-col gap-4 max-w-2xl">
          <button
            onClick={() => setStepOverride(1)}
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted hover:text-primary transition-colors self-start px-2 py-1.5 rounded-lg"
          >
            <ArrowLeft className="w-4 h-4" /> Back to criteria
          </button>

          <CandidateUploadPanel
            profileId={profileId}
            actionLabel="Upload & Start Screening"
            onUploadStart={handleUploadStart}
            onUploaded={handleUploadedAndScreen}
            onUploadError={handleUploadError}
          />

          {hasCandidates && (
            <div className="bg-accent/40 border border-border rounded-lg px-4 py-3 flex items-center flex-wrap justify-between gap-3">
              <p className="text-sm font-normal text-foreground">
                {candidates!.length} candidate{candidates!.length === 1 ? '' : 's'} already uploaded for this profile.
                Re-uploading the same roster replaces them.
              </p>
              <button
                onClick={() => setStepOverride(3)}
                className="text-sm font-semibold text-primary flex items-center gap-1.5 shrink-0 px-2 py-1.5 rounded-lg"
              >
                Skip to results <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* ---------------- STEP 3: RESULTS ---------------- */}
      {step === 3 && (
        <div className="flex flex-col gap-6">
          <ResumeFetchPanel profileId={profileId} />
          {/* Phase banner: uploading -> screening -> done */}
          {uploadPhase === 'uploading' && (
            <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 sm:p-6 flex items-center gap-4">
              <Loader2 className="w-8 h-8 text-primary animate-spin shrink-0" />
              <div>
                <p className="text-base font-semibold text-foreground">Uploading candidates & matching documents…</p>
                <p className="text-sm text-muted font-normal mt-0.5">
                  Screening will start automatically as soon as the upload finishes — you can stay on this screen.
                </p>
              </div>
            </div>
          )}

          {uploadPhase === 'error' && (
            <div className="bg-danger/10 border border-danger/20 rounded-lg p-4 sm:p-6 flex items-start gap-4">
              <AlertTriangle className="w-6 h-6 text-danger shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-base font-semibold text-danger">Upload failed</p>
                <p className="text-sm text-foreground font-normal mt-0.5">{uploadPhaseError}</p>
              </div>
              <button
                onClick={() => {
                  setUploadPhase('idle');
                  setStepOverride(2);
                }}
                className="bg-card border border-border font-semibold text-sm px-5 py-2.5 rounded-lg text-foreground hover:border-primary/40 shrink-0"
              >
                Back to upload
              </button>
            </div>
          )}

          {runActive && run && run.total_candidates > 0 && (
            <div className="bg-primary/5 border border-primary/20 rounded-lg p-4 sm:p-6 flex flex-col gap-3">
              <div className="flex items-center gap-4">
                <Loader2 className="w-8 h-8 text-primary animate-spin shrink-0" />
                <div className="flex-1">
                  <p className="text-base font-semibold text-foreground">
                    {run.status === 'stopping'
                      ? 'Stopping — finishing candidates already in progress…'
                      : 'Screening candidates against the JD criteria…'}{' '}
                    {run.processed_count}/{run.total_candidates} done
                    {run.failed_count > 0 ? ` · ${run.failed_count} failed` : ''}
                  </p>
                  <p className="text-sm text-muted font-normal mt-0.5">
                    Each candidate's declared data and documents are being verified. Results appear in the table below as they finish.
                  </p>
                </div>
                <span className="text-2xl font-bold text-primary shrink-0">
                  {Math.round((run.processed_count / run.total_candidates) * 100)}%
                </span>
                <button
                  onClick={() => stopScreening.mutate(run.id)}
                  disabled={run.status === 'stopping' || stopScreening.isPending}
                  className="bg-card border border-danger/30 text-danger font-semibold text-sm px-4 py-2 rounded-lg flex items-center gap-2 hover:bg-danger/5 disabled:opacity-50 shrink-0"
                  title="Stop screening — candidates not yet started keep their previous result"
                >
                  <Square className="w-4 h-4" />
                  {run.status === 'stopping' ? 'Stopping…' : 'Stop'}
                </button>
              </div>
              <div className="h-2.5 bg-accent rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${(run.processed_count / run.total_candidates) * 100}%` }}
                />
              </div>
            </div>
          )}

          {outdatedCount > 0 && !runActive && uploadPhase !== 'uploading' && (
            <div className="bg-warning/10 border border-warning/25 rounded-lg p-4 flex items-center gap-3 flex-wrap">
              <AlertTriangle className="w-5 h-5 text-warning shrink-0" />
              <p className="text-sm text-foreground flex-1 min-w-0 sm:min-w-[240px]">
                <span className="font-semibold">{outdatedCount} result{outdatedCount === 1 ? ' was' : 's were'}</span>{' '}
                produced before the criteria were last edited — {outdatedCount === 1 ? 'it doesn’t' : 'they don’t'}{' '}
                reflect the current criteria until re-screened.
              </p>
              <button
                onClick={() => setRescreenScope({})}
                className="bg-card border border-border text-foreground font-semibold text-sm px-4 py-2 rounded-lg flex items-center gap-2 hover:border-primary/40 shrink-0"
              >
                <RotateCcw className="w-4 h-4" /> Review &amp; re-screen
              </button>
            </div>
          )}

          {/* Actions + summary */}
          <div className="bg-card border border-border rounded-lg p-4 sm:p-6 shadow-sm flex flex-col gap-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-4 flex-wrap">
                {(['eligible', 'needs_review', 'not_eligible', 'not_evaluated'] as const).map((s) => (
                  <div key={s} className="flex items-center gap-1.5">
                    <StatusBadge status={s} />
                    <span className="text-base font-bold text-foreground">{statusCounts[s] ?? 0}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setStepOverride(2)}
                  className="bg-card border border-border text-foreground font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 hover:border-primary/40"
                >
                  <UploadCloud className="w-4 h-4" /> Upload more
                </button>
                <button
                  onClick={() => setAddCandidateOpen(true)}
                  className="bg-card border border-border text-foreground font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 hover:border-primary/40"
                  title="Manually add one candidate (walk-in / late application)"
                >
                  <Plus className="w-4 h-4" /> Add candidate
                </button>
                {(statusCounts['not_evaluated'] ?? 0) > 0 && (
                  <button
                    onClick={() => handleStartScreening(false)}
                    disabled={startScreening.isPending || runActive || uploadPhase === 'uploading'}
                    className="bg-primary text-primary-foreground font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50"
                    title="Screen only candidates without a result yet — candidates who already have one are left untouched"
                  >
                    <Play className="w-4 h-4" />
                    Screen unscreened ({statusCounts['not_evaluated']})
                  </button>
                )}
                <button
                  onClick={() => setRescreenScope({})}
                  disabled={startScreening.isPending || runActive || uploadPhase === 'uploading'}
                  className="bg-card border border-border text-foreground font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 hover:border-primary/40 disabled:opacity-50"
                  title="Re-evaluate every candidate, including those that already have a result (e.g. after editing criteria)"
                >
                  <RotateCcw className="w-4 h-4" /> Re-screen all
                </button>
                <button
                  onClick={async () => {
                    const count = candidates?.length ?? 0;
                    if (!confirm(
                      `Delete all ${count} candidate${count === 1 ? '' : 's'} for this JD?\n\n` +
                      'Their documents and screening results are removed permanently. ' +
                      'The JD and its criteria stay saved, so you can upload a fresh batch right away.'
                    )) return;
                    try {
                      await resetCandidates.mutateAsync(undefined);
                      setRunId(null);
                      setStepOverride(2);
                    } catch (err: any) {
                      alert(`Could not delete candidates: ${err?.detail || err?.message || 'Unknown error'}`);
                    }
                  }}
                  disabled={resetCandidates.isPending || runActive || uploadPhase === 'uploading'}
                  className="bg-card border border-danger/30 text-danger font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 hover:bg-danger/5 disabled:opacity-50"
                  title="Remove every candidate but keep the JD and criteria"
                >
                  <Trash2 className="w-4 h-4" />
                  {resetCandidates.isPending ? 'Deleting…' : 'Delete all candidates'}
                </button>
              </div>
            </div>

            {screeningError && (
              <p className="text-sm font-medium text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                {screeningError}
              </p>
            )}

            {run && run.total_candidates === 0 && (
              <p className="text-sm font-normal text-muted">
                Everyone already has a result — use Re-screen all to re-evaluate all candidates against the current criteria.
              </p>
            )}

            {run && run.total_candidates > 0 && !runActive && (
              <div className="flex items-center justify-between text-sm font-medium text-foreground">
                <span>
                  Screening {run.status === 'stopped' ? 'stopped' : 'finished'} — {run.processed_count}/{run.total_candidates} candidates processed
                  {run.status === 'stopped' ? ' (the rest keep their previous result)' : ''}
                  {run.failed_count > 0 ? ` · ${run.failed_count} failed` : ''}
                </span>
                <div className="flex items-center gap-2">
                  {run.remaining_candidates ? (
                    <button
                      onClick={() => handleContinueScreening(run.id)}
                      disabled={continueScreening.isPending || uploadPhase === 'uploading'}
                      className="bg-primary text-primary-foreground font-semibold text-sm px-4 py-2 rounded-lg flex items-center gap-2 disabled:opacity-50"
                    >
                      <Play className="w-4 h-4" /> Continue ({run.remaining_candidates} remaining)
                    </button>
                  ) : null}
                  <StatusBadge status={run.status} />
                </div>
              </div>
            )}
            {run?.error_message && (
              <p className="text-sm font-medium text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
                Error: {run.error_message}
              </p>
            )}
          </div>

          {/* Candidate list */}
          <div className="bg-card border border-border rounded-lg shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-border">
              <h2 className="font-semibold text-base text-foreground">Candidates</h2>
              <div className="flex items-center gap-2">
                {candidates && candidates.length > 0 && (
                  <span className="text-sm font-medium px-2.5 py-1 bg-primary/10 text-primary border border-primary/20 rounded-md">
                    {candidates.length} total
                  </span>
                )}
              </div>
            </div>

            {!candidates || candidates.length === 0 ? (
              <div className="px-4 sm:px-6 py-10 text-center flex flex-col items-center gap-2">
                <div className="w-10 h-10 rounded-lg bg-accent border border-border flex items-center justify-center">
                  <Users className="w-5 h-5 text-muted" />
                </div>
                <p className="text-base font-semibold text-foreground">No candidates yet</p>
                <p className="text-sm text-muted font-normal">Go to Step 2 to upload the candidate roster.</p>
              </div>
            ) : (
              <>
                <div className="px-4 sm:px-6 py-3 border-b border-border">
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="relative max-w-md flex-1 min-w-0 sm:min-w-[220px]">
                      <Search className="w-4 h-4 text-muted absolute left-3 top-1/2 -translate-y-1/2" />
                      <input
                        type="text"
                        value={candidateSearch}
                        onChange={(e) => setCandidateSearch(e.target.value)}
                        placeholder="Search by name, ID or email…"
                        className="w-full bg-card border border-border text-foreground text-sm font-normal rounded-lg pl-9 pr-3 py-2.5 placeholder:text-muted"
                      />
                    </div>
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-2.5 cursor-pointer"
                      title="Filter candidates by screening status"
                    >
                      <option value="all">All ({runScopedCandidates.length})</option>
                      <option value="eligible">Eligible ({scopedStatusCounts['eligible'] ?? 0})</option>
                      <option value="not_evaluated">Not screened yet ({scopedStatusCounts['not_evaluated'] ?? 0})</option>
                      <option value="needs_review">Manual review ({scopedStatusCounts['needs_review'] ?? 0})</option>
                      <option value="not_eligible">Not eligible ({scopedStatusCounts['not_eligible'] ?? 0})</option>
                    </select>
                    <select
                      value={resumeFilter}
                      onChange={(e) => setResumeFilter(e.target.value)}
                      className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-2.5 cursor-pointer"
                      title="Filter candidates by the state of their resume"
                    >
                      <option value="all">All resumes</option>
                      <option value="fetched">Resume fetched ({resumeCounts['fetched'] ?? 0})</option>
                      <option value="pending">Not fetched yet ({resumeCounts['pending'] ?? 0})</option>
                      <option value="failed">Fetch failed ({resumeCounts['failed'] ?? 0})</option>
                      <option value="no_link">No resume link ({resumeCounts['no_link'] ?? 0})</option>
                    </select>
                    <select
                      value={ranked ? 'ranked' : 'roster'}
                      onChange={(e) => setOrderChoice(e.target.value as 'ranked' | 'roster')}
                      className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-2.5 cursor-pointer"
                      title="Order the list best-first by score, or in the original roster order"
                    >
                      <option value="ranked">Ranked: best first</option>
                      <option value="roster">Roster order</option>
                    </select>
                    {screeningRuns && screeningRuns.length > 0 && (
                      <select
                        value={runFilter}
                        onChange={(e) => setRunFilter(e.target.value)}
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
                    {selectedRun && (
                      <>
                        <button
                          onClick={() => setRescreenScope({ runId: selectedRun.id })}
                          disabled={startScreening.isPending || runActive || uploadPhase === 'uploading' || runScopedCandidates.length === 0}
                          className="bg-card border border-border text-foreground font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center gap-1.5 hover:border-primary/40 disabled:opacity-50 shrink-0"
                          title="Re-evaluate only this screening's candidates against the current criteria"
                        >
                          <RotateCcw className="w-4 h-4" />
                          Re-screen these ({runScopedCandidates.length})
                        </button>
                        <button
                          onClick={async () => {
                            const count = runScopedCandidates.length;
                            if (!confirm(
                              `Delete the ${count} candidate${count === 1 ? '' : 's'} from the screening of ${formatDateTime(selectedRun.started_at)}?\n\n` +
                              'Only those candidates (and that screening\'s history entry) are removed permanently — everyone else stays.'
                            )) return;
                            try {
                              await resetCandidates.mutateAsync(selectedRun.id);
                              setRunFilter('all');
                            } catch (err: any) {
                              alert(`Could not delete candidates: ${err?.detail || err?.message || 'Unknown error'}`);
                            }
                          }}
                          disabled={resetCandidates.isPending || runActive || uploadPhase === 'uploading' || runScopedCandidates.length === 0}
                          className="bg-card border border-danger/30 text-danger font-semibold text-sm px-4 py-2.5 rounded-lg flex items-center gap-1.5 hover:bg-danger/5 disabled:opacity-50 shrink-0"
                          title="Remove only this screening's candidates"
                        >
                          <Trash2 className="w-4 h-4" />
                          {resetCandidates.isPending ? 'Deleting…' : `Delete these (${runScopedCandidates.length})`}
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {filteredCandidates.length === 0 ? (
                  <div className="px-4 sm:px-6 py-8 text-center">
                    <p className="text-sm font-normal text-foreground">No candidates match your search or filter.</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-accent/60 border-b border-border text-left">
                          {ranked && <th className="py-3 px-5 text-sm font-semibold text-foreground">#</th>}
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Candidate</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Score</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Skills match</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Email</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Documents</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Certificates in CV</th>
                          <th className="py-3 px-5 text-sm font-semibold text-foreground">Status</th>
                          <th className="py-3 px-5" />
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCandidates.map((c, i) => (
                          <tr key={c.id} className={`border-b border-border/60 hover:bg-accent/40 transition-colors ${i % 2 !== 0 ? 'bg-accent/20' : ''}`}>
                            {ranked && <td className="py-3 px-5 text-muted font-semibold">{i + 1}</td>}
                            <td className="py-3 px-5">
                              <p className="font-medium text-foreground">{c.name || 'Unnamed candidate'}</p>
                              <p className="text-xs text-muted font-normal mt-0.5">{c.external_id}</p>
                            </td>
                            <td className="py-3 px-5 font-semibold text-foreground">
                              {c.suitability_score != null ? c.suitability_score : '—'}
                            </td>
                            <td className="py-3 px-5 font-semibold text-foreground">
                              {c.skill_match_percentage != null ? `${c.skill_match_percentage}%` : '—'}
                            </td>
                            <td className="py-3 px-5 font-normal text-foreground">{c.email || '—'}</td>
                            <td className="py-3 px-5">
                              {c.resume_fetch_status ? (
                                <div title={c.resume_fetch_error ?? undefined}>
                                  <StatusBadge status={c.resume_fetch_status} />
                                  {c.resume_fetch_status === 'failed' && c.resume_fetch_error && (
                                    <p className="text-xs text-muted font-normal mt-1 max-w-[16rem]">{c.resume_fetch_error}</p>
                                  )}
                                </div>
                              ) : (
                                <StatusBadge status={c.ingestion_status} />
                              )}
                            </td>
                            <td className="py-3 px-5 align-top">
                              <CertificatesCell certifications={c.cv_certifications} screened={c.status !== 'not_evaluated'} />
                            </td>
                            <td className="py-3 px-5">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <StatusBadge status={resultGroup(c)} />
                                {c.gov_tag && <StatusBadge status="gov_tag" />}
                                {c.review_tag && resultGroup(c) === c.status && (
                                  <span title={c.review_note ?? undefined}><StatusBadge status={c.review_tag} /></span>
                                )}
                                {c.status_overridden && (
                                  <span className="text-xs font-medium text-warning bg-warning/10 border border-warning/20 rounded-md px-1.5 py-0.5">edited</span>
                                )}
                              </div>
                              {c.review_note && c.review_tag && (
                                <p className="text-xs text-muted font-normal mt-1 max-w-[18rem]">{c.review_note}</p>
                              )}
                            </td>
                            <td className="py-3 px-5 text-right">
                              <Link to={`/candidate/${profile.id}/${c.id}`} className="text-sm font-semibold text-primary hover:underline">
                                Review →
                              </Link>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>

        </div>
      )}

      {addCandidateOpen && (
        <AddCandidateModal profileId={profileId} onClose={() => setAddCandidateOpen(false)} />
      )}
      {rescreenScope && (
        <RescreenDialog
          candidates={(candidates ?? []).filter((c) => !rescreenScope.runId || c.last_screening_run_id === rescreenScope.runId)}
          screeningRuns={screeningRuns ?? []}
          scopeLabel={
            rescreenScope.runId && selectedRun ? `the screening of ${formatDateTime(selectedRun.started_at)}` : undefined
          }
          resumableRun={rescreenScope.runId ? undefined : resumableRun}
          busy={startScreening.isPending || continueScreening.isPending || runActive}
          onContinue={handleContinueScreening}
          onRescreenOutdated={() => handleStartScreening(true, rescreenScope.runId, true)}
          onRescreenAll={() => handleStartScreening(true, rescreenScope.runId)}
          onClose={() => setRescreenScope(null)}
        />
      )}
    </div>
  );
};

export default ProfileDetailPage;
