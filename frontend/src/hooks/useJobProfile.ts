import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Criterion, CriterionCreate, CriterionUpdate, JobProfile } from '../types';

export function useJobProfile(profileId?: string) {
  return useQuery<JobProfile>({
    queryKey: ['job-profile', profileId],
    queryFn: () => api.get(`/jd/profiles/${profileId}`),
    enabled: !!profileId,
  });
}

function useInvalidateProfile(profileId?: string) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ['job-profile', profileId] });
    // Criteria counts shown on the list page can change too.
    queryClient.invalidateQueries({ queryKey: ['job-profiles'] });
    // Skill weights / the related mark / screening settings re-score the
    // saved results on the server, so statuses and scores can move.
    queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
    queryClient.invalidateQueries({ queryKey: ['results', profileId] });
    queryClient.invalidateQueries({ queryKey: ['candidate-review', profileId] });
  };
}

export function useAddCriterion(profileId?: string) {
  const invalidate = useInvalidateProfile(profileId);
  return useMutation<Criterion, Error, CriterionCreate>({
    mutationFn: (payload) => api.post(`/jd/profiles/${profileId}/criteria`, payload),
    onSuccess: invalidate,
  });
}

export function useUpdateCriterion(profileId?: string) {
  const invalidate = useInvalidateProfile(profileId);
  return useMutation<Criterion, Error, { criterionId: string; payload: CriterionUpdate }>({
    mutationFn: ({ criterionId, payload }) =>
      api.patch(`/jd/profiles/${profileId}/criteria/${criterionId}`, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteCriterion(profileId?: string) {
  const invalidate = useInvalidateProfile(profileId);
  return useMutation<null, Error, string>({
    mutationFn: (criterionId) => api.delete(`/jd/profiles/${profileId}/criteria/${criterionId}`),
    onSuccess: invalidate,
  });
}

export interface ProfileSettings {
  experience_tolerance_years?: number;
  exception_skills_threshold?: number;
  weight_skills?: number;
  weight_experience?: number;
  weight_desirable?: number;
  /** null switches that section's close-miss check off. */
  close_miss_skills_min?: number | null;
  close_miss_experience_min?: number | null;
  close_miss_desirable_min?: number | null;
  rank_by_suitability?: boolean;
}

/** Saves the post's screening settings (experience tolerance, exception threshold, ranking weights). */
export function useUpdateProfileSettings(profileId?: string) {
  const invalidate = useInvalidateProfile(profileId);
  return useMutation<JobProfile, Error, ProfileSettings>({
    mutationFn: (payload) => api.patch(`/jd/profiles/${profileId}/settings`, payload),
    onSuccess: invalidate,
  });
}
