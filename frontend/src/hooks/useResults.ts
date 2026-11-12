import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { ResultsResponse } from '../types';

export function useResults(profileId?: string, status?: string, runId?: string, ranked = false) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (runId) params.set('run_id', runId);
  params.set('sort', ranked ? 'skill_match' : 'roster');
  const query = params.toString() ? `?${params.toString()}` : '';
  return useQuery<ResultsResponse>({
    queryKey: ['results', profileId, status, runId, ranked],
    queryFn: () => api.get(`/jd/profiles/${profileId}/results${query}`),
    enabled: !!profileId,
  });
}
