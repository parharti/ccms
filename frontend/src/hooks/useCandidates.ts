import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Candidate, CandidateUploadSummary, ResumeFetchStatus } from '../types';

export function useCandidates(profileId?: string) {
  return useQuery<Candidate[]>({
    queryKey: ['candidates', profileId],
    queryFn: () => api.get(`/jd/profiles/${profileId}/candidates`),
    enabled: !!profileId,
  });
}

export function useUploadCandidates(profileId?: string) {
  const queryClient = useQueryClient();

  return useMutation<CandidateUploadSummary, Error, { excelFile: File; masterZipFile?: File | null; templateId?: string }>({
    mutationFn: ({ excelFile, masterZipFile, templateId }) => {
      const formData = new FormData();
      formData.append('excel_file', excelFile);
      // No ZIP = roster-only upload: the sheet alone is enough, resumes are
      // fetched later from its links (see useFetchResumes).
      if (!masterZipFile) {
        return api.post(`/jd/profiles/${profileId}/candidates/upload-roster`, formData, { isFormData: true });
      }
      formData.append('master_zip_file', masterZipFile);
      if (templateId) formData.append('template_id', templateId);
      return api.post(`/jd/profiles/${profileId}/candidates/upload`, formData, { isFormData: true });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
    },
  });
}

/** Deletes candidates: all of them, or — when a runId is passed — only
 * those last screened in that run (plus the run's history entry). */
export function useResetCandidates(profileId?: string) {
  const queryClient = useQueryClient();

  return useMutation<{ deleted: number }, Error, string | undefined>({
    mutationFn: (runId?: string) =>
      api.delete(`/jd/profiles/${profileId}/candidates${runId ? `?run_id=${runId}` : ''}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
      queryClient.invalidateQueries({ queryKey: ['results', profileId] });
      queryClient.invalidateQueries({ queryKey: ['screening-runs', profileId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] });
    },
  });
}

/** Resume-fetch progress for a roster-only profile; polls while downloads run. */
export function useResumeFetchStatus(profileId?: string) {
  return useQuery<ResumeFetchStatus>({
    queryKey: ['resume-fetch-status', profileId],
    queryFn: () => api.get(`/jd/profiles/${profileId}/candidates/fetch-resumes/status`),
    enabled: !!profileId,
    refetchInterval: (query) => ((query.state.data?.fetching ?? 0) > 0 ? 3000 : false),
  });
}

function invalidateResumeData(queryClient: ReturnType<typeof useQueryClient>, profileId?: string) {
  queryClient.invalidateQueries({ queryKey: ['resume-fetch-status', profileId] });
  queryClient.invalidateQueries({ queryKey: ['candidates', profileId] });
  queryClient.invalidateQueries({ queryKey: ['results', profileId] });
  queryClient.invalidateQueries({ queryKey: ['dashboard-summary'] });
}

/** Downloads resumes (and re-screens) for shortlisted candidates only. */
export function useFetchResumes(profileId?: string) {
  const queryClient = useQueryClient();
  return useMutation<{ queued: number }, Error, { retryFailed?: boolean } | void>({
    mutationFn: (opts) =>
      api.post(`/jd/profiles/${profileId}/candidates/fetch-resumes?retry_failed=${opts?.retryFailed ? 'true' : 'false'}`),
    onSuccess: () => invalidateResumeData(queryClient, profileId),
  });
}

/** Fallback: ZIP of resume PDFs matched to candidates by name / email / phone in the file name. */
export function useUploadResumesZip(profileId?: string) {
  const queryClient = useQueryClient();
  return useMutation<{ matched: number; unmatched_files: string[] }, Error, File>({
    mutationFn: (zip) => {
      const formData = new FormData();
      formData.append('resumes_zip', zip);
      return api.post(`/jd/profiles/${profileId}/candidates/resumes-zip`, formData, { isFormData: true });
    },
    onSuccess: () => invalidateResumeData(queryClient, profileId),
  });
}
