import React, { useState } from 'react';
import { FileSpreadsheet, Loader2, Plus, Trash2, AlertTriangle } from 'lucide-react';
import {
  useCreateDepartmentTemplate,
  useDeleteDepartmentTemplate,
  useDepartmentTemplates,
  useInspectSheet,
} from '../hooks/useDepartmentTemplates';
import { ApiError } from '../context/AuthContext';
import { TEMPLATE_FIELDS, type EvidenceMode, type SheetInspection } from '../types';

const NONE = '';

/**
 * Lists the department templates and lets an admin add one: upload a blank
 * or sample sheet, pick which column plays which role. No AI involved --
 * the admin knows the department's sheet.
 */
export const TemplateManager: React.FC = () => {
  const { data: templates } = useDepartmentTemplates();
  const inspect = useInspectSheet();
  const create = useCreateDepartmentTemplate();
  const remove = useDeleteDepartmentTemplate();

  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [sheet, setSheet] = useState<SheetInspection | null>(null);
  const [fieldMap, setFieldMap] = useState<Record<string, string>>({});
  const [evidenceMode, setEvidenceMode] = useState<EvidenceMode>('declared_primary');
  const [resumePatterns, setResumePatterns] = useState('resume, cv');
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setOpen(false);
    setName('');
    setSheet(null);
    setFieldMap({});
    setEvidenceMode('declared_primary');
    setResumePatterns('resume, cv');
    setError(null);
  };

  const errorText = (err: unknown) => (err instanceof ApiError ? err.detail : 'Something went wrong. Please try again.');

  const handleSheet = async (file: File | null) => {
    if (!file) return;
    setError(null);
    try {
      setSheet(await inspect.mutateAsync(file));
    } catch (err) {
      setError(errorText(err));
    }
  };

  const handleSave = async () => {
    setError(null);
    try {
      await create.mutateAsync({
        name: name.trim(),
        field_map: Object.fromEntries(TEMPLATE_FIELDS.map((f) => [f.key, fieldMap[f.key] || null])),
        header_row: sheet?.header_row ?? null,
        document_columns: {},
        resume_filename_patterns: resumePatterns.split(',').map((s) => s.trim()).filter(Boolean),
        evidence_mode: evidenceMode,
      });
      reset();
    } catch (err) {
      setError(errorText(err));
    }
  };

  const canSave = name.trim() && sheet && fieldMap.external_id && resumePatterns.trim();

  return (
    <div className="bg-card border border-border rounded-lg p-6 shadow-sm flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="w-4.5 h-4.5 text-primary" />
          <h2 className="font-semibold text-base text-foreground">Department templates</h2>
        </div>
        {!open && (
          <button
            onClick={() => setOpen(true)}
            className="text-sm font-semibold px-3 py-2 rounded-lg border border-border hover:border-primary/40 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> New template
          </button>
        )}
      </div>
      <p className="text-sm text-muted font-normal leading-relaxed">
        A template tells the system how a department's candidate sheet is laid out, so each department
        can keep its own column names.
      </p>

      <ul className="flex flex-col gap-2">
        {templates?.map((t) => (
          <li key={t.id} className="flex items-center justify-between gap-3 border border-border rounded-lg px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground">{t.name}</p>
              <p className="text-sm text-muted font-normal truncate">
                {t.evidence_mode === 'declared_primary'
                  ? 'Application data + resume are the evidence'
                  : 'Uploaded documents are the proof'}
                {t.description ? ` · ${t.description}` : ''}
              </p>
            </div>
            <button
              onClick={() => {
                if (window.confirm(`Delete the "${t.name}" template? Already uploaded candidates are not affected.`)) {
                  remove.mutate(t.id);
                }
              }}
              className="text-muted hover:text-danger p-2 rounded-lg"
              title="Delete template"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </li>
        ))}
      </ul>

      {open && (
        <div className="border border-primary/30 rounded-lg p-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold text-foreground">Template name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Ministry of X"
              className="bg-card border border-border text-sm rounded-lg px-3 py-2.5"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold text-foreground">Blank or sample sheet</span>
            <input
              type="file"
              accept=".xlsx,.xls,.csv,.txt"
              onChange={(e) => handleSheet(e.target.files?.[0] ?? null)}
              className="text-sm"
            />
            {inspect.isPending && (
              <span className="text-sm text-muted flex items-center gap-1.5"><Loader2 className="w-4 h-4 animate-spin" /> Reading columns…</span>
            )}
          </label>

          {sheet && (
            <>
              <div className="flex flex-col gap-3">
                {TEMPLATE_FIELDS.map((f) => (
                  <label key={f.key} className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-foreground">
                      {f.label}{f.required ? ' *' : ''}
                    </span>
                    <select
                      value={fieldMap[f.key] ?? NONE}
                      onChange={(e) => setFieldMap((m) => ({ ...m, [f.key]: e.target.value }))}
                      className="bg-card border border-border text-sm rounded-lg px-3 py-2 max-w-[55%]"
                    >
                      <option value={NONE}>— not in this sheet —</option>
                      {sheet.headers.map((h) => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <p className="text-sm text-muted font-normal">
                Every other column is still sent to the screening as application data.
              </p>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold text-foreground">Resume file name contains</span>
                <input
                  value={resumePatterns}
                  onChange={(e) => setResumePatterns(e.target.value)}
                  className="bg-card border border-border text-sm rounded-lg px-3 py-2.5"
                />
                <span className="text-sm text-muted font-normal">Comma-separated. Identifies the resume inside each candidate's folder.</span>
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold text-foreground">What counts as evidence?</span>
                <select
                  value={evidenceMode}
                  onChange={(e) => setEvidenceMode(e.target.value as EvidenceMode)}
                  className="bg-card border border-border text-sm rounded-lg px-3 py-2.5"
                >
                  <option value="declared_primary">Application data + resume (no proof documents collected)</option>
                  <option value="documents_primary">Uploaded certificates and letters are the proof</option>
                </select>
              </label>
            </>
          )}

          {error && (
            <div className="p-3 bg-danger/10 border border-danger/20 text-danger rounded-lg flex items-start gap-2 text-sm font-medium">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex gap-2 justify-end">
            <button onClick={reset} className="text-sm font-semibold px-4 py-2.5 rounded-lg border border-border">Cancel</button>
            <button
              onClick={handleSave}
              disabled={!canSave || create.isPending}
              className="bg-primary text-primary-foreground font-semibold text-sm px-5 py-2.5 rounded-lg disabled:opacity-50"
            >
              {create.isPending ? 'Saving…' : 'Save template'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default TemplateManager;
