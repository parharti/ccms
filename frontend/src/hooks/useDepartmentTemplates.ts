import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { DepartmentTemplate, DepartmentTemplateInput, SheetInspection } from '../types';

export function useDepartmentTemplates() {
  return useQuery<DepartmentTemplate[]>({
    queryKey: ['department-templates'],
    queryFn: () => api.get('/department-templates'),
  });
}

/** Reads the column headers of a blank/sample sheet (nothing is saved). */
export function useInspectSheet() {
  return useMutation<SheetInspection, Error, File>({
    mutationFn: (file) => {
      const formData = new FormData();
      formData.append('file', file);
      return api.post('/department-templates/inspect', formData, { isFormData: true });
    },
  });
}

export function useCreateDepartmentTemplate() {
  const queryClient = useQueryClient();
  return useMutation<DepartmentTemplate, Error, DepartmentTemplateInput>({
    mutationFn: (body) => api.post('/department-templates', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['department-templates'] }),
  });
}

export function useDeleteDepartmentTemplate() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (id) => api.delete(`/department-templates/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['department-templates'] }),
  });
}
