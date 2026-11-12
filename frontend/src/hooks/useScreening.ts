import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
// useQueryClient is used by the screening mutations below
import { api } from '../lib/api';
import type { CandidateEvaluationResult, ScreeningRun } from '../types';

export function useStartScreening(profileId?: string) {
  const queryClient = useQueryClient();

  return useMutation<ScreeningRun, Error, { force?: boolean; runId?: string; outdated?: boolean } | undefined>({
    mutationFn: (opts) => {
      const params = new URLSearchParams();
      if (opts?.force) params.set('force', 'true');
      if (opts?.runId) params.set('run_id', opts.runId);
      if (opts?.outdated) params.set('outdated', 'true');
      const query = params.toString() ? `?${params.toString()}` : '';
      return api.post(`/jd/profiles/${profileId}/screen${query}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
    },
  });
}

/**
 * Polls a screening run's progress every 1.5s while it's still running,
 * and stops polling once it's completed. Pass `runId: null` to disable.
 *
 * Invalidation after completion is handled by a useEffect in the
 * consuming component — NOT here. select() runs on every render and is
 * a data transformer, not a side-effect hook; putting invalidateQueries
 * inside it causes it to fire repeatedly and unreliably.
 */
export function useScreeningRun(profileId?: string, runId?: string | null) {
  return useQuery<ScreeningRun>({
    queryKey: ['screening-run', profileId, runId],
    queryFn: () => api.get(`/jd/profiles/${profileId}/screening-runs/${runId}`),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' || query.state.data?.status === 'stopping' ? 1500 : false,
  });
}

/**
 * Continues a stopped run in place with only the candidates it never
 * reached; the run goes back to "running" and keeps its counts.
 */
export function useContinueScreening(profileId?: string) {
  const queryClient = useQueryClient();
  return useMutation<ScreeningRun, Error, string>({
    mutationFn: (runId: string) => api.post(`/jd/profiles/${profileId}/screening-runs/${runId}/continue`),
    onSuccess: (run) => {
      queryClient.setQueryData(['screening-run', profileId, run.id], run);
      queryClient.invalidateQueries({ queryKey: ['screening-runs', profileId] });
    },
  });
}

/**
 * Stops a running batch: candidates not yet started are skipped, ones
 * already being evaluated finish first (status "stopping" -> "stopped").
 */
export function useStopScreening(profileId?: string) {
  const queryClient = useQueryClient();
  return useMutation<ScreeningRun, Error, string>({
    mutationFn: (runId: string) => api.post(`/jd/profiles/${profileId}/screening-runs/${runId}/stop`),
    onSuccess: (run) => {
      queryClient.setQueryData(['screening-run', profileId, run.id], run);
    },
  });
}

/**
 * All batch screening runs for a profile, newest first — powers the
 * "show only this screening" filter on the Results screens.
 */
export function useScreeningRuns(profileId?: string) {
  return useQuery<ScreeningRun[]>({
    queryKey: ['screening-runs', profileId],
    queryFn: () => api.get(`/jd/profiles/${profileId}/screening-runs`),
    enabled: !!profileId,
  });
}

export function useEvaluateCandidate(profileId?: string) {
  const queryClient = useQueryClient();
  return useMutation<CandidateEvaluationResult, Error, string>({
    mutationFn: (candidateId: string) =>
      api.post(`/jd/profiles/${profileId}/candidates/${candidateId}/evaluate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
      queryClient.invalidateQueries({ queryKey: ['candidate-review', profileId] });
    },
  });
}
