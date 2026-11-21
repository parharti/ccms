import React, { useEffect, useState } from 'react';
import { Loader2, Plus, Save, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useUpdateProfileSettings } from '../hooks/useJobProfile';
import { ApiError } from '../context/AuthContext';
import type { Competency, JobProfile } from '../types';

interface NumberFieldProps {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  step?: string;
  placeholder?: string;
}

const NumberField: React.FC<NumberFieldProps> = ({ label, hint, value, onChange, step = '1', placeholder }) => (
  <label className="flex flex-col gap-1">
    <span className="text-sm font-semibold text-foreground">{label}</span>
    <input
      type="number"
      min={0}
      step={step}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-2 w-full"
    />
    <span className="text-xs text-muted font-normal">{hint}</span>
  </label>
);

interface MarksRowProps {
  name: string;
  value: string;
  onValue: (v: string) => void;
  /** Editable name + remove button for HR's own fields; fixed rows omit these. */
  onName?: (v: string) => void;
  onRemove?: () => void;
}

const MarksRow: React.FC<MarksRowProps> = ({ name, value, onValue, onName, onRemove }) => (
  <li className="flex items-center gap-2 px-3 py-2">
    {onName ? (
      <input
        value={name}
        onChange={(e) => onName(e.target.value)}
        placeholder="Field name, e.g. Problem solving"
        className="bg-card border border-border text-foreground text-sm font-medium rounded-lg px-3 py-1.5 flex-1 min-w-0"
      />
    ) : (
      <span className="text-sm font-medium text-foreground flex-1 min-w-0 px-3">{name}</span>
    )}
    <input
      type="number"
      min={0}
      max={100}
      value={value}
      onChange={(e) => onValue(e.target.value)}
      aria-label={`${name || 'Field'} marks`}
      className="bg-card border border-border text-foreground text-sm font-semibold rounded-lg px-2 py-1.5 w-20 text-right tabular-nums"
    />
    {onRemove ? (
      <button type="button" onClick={onRemove} aria-label={`Remove ${name}`} className="p-1.5 text-muted hover:text-danger">
        <Trash2 className="w-4 h-4" />
      </button>
    ) : (
      <span className="w-7" />
    )}
  </li>
);

/**
 * Per-post screening settings: how far an experience shortfall may go before
 * rejection (with strong skills it becomes "strong candidate, with
 * exception"), and the weights of the suitability score that ranks the
 * eligible candidates. Applies on the next screening.
 */
export const ScreeningSettingsCard: React.FC<{ profile: JobProfile }> = ({ profile }) => {
  const update = useUpdateProfileSettings(profile.id);
  const [tolerance, setTolerance] = useState('2');
  const [threshold, setThreshold] = useState('80');
  const [wSkills, setWSkills] = useState('40');
  const [wDesirable, setWDesirable] = useState('15');
  const [competencies, setCompetencies] = useState<Competency[]>([]);
  const [rankDefault, setRankDefault] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setTolerance(String(profile.experience_tolerance_years ?? 2));
    setThreshold(String(profile.exception_skills_threshold ?? 80));
    setWSkills(String(profile.weight_skills ?? 40));
    setWDesirable(String(profile.weight_desirable ?? 15));
    setCompetencies((profile.competencies ?? []).map((c) => ({ ...c })));
    setRankDefault(profile.rank_by_suitability ?? true);
  }, [
    profile.competencies,
    profile.experience_tolerance_years,
    profile.exception_skills_threshold,
    profile.weight_skills,
    profile.weight_desirable,
    profile.rank_by_suitability,
  ]);


  const save = async () => {
    setSaved(false);
    try {
      await update.mutateAsync({
        experience_tolerance_years: Number(tolerance),
        exception_skills_threshold: Number(threshold),
        weight_skills: Number(wSkills),
        weight_desirable: Number(wDesirable),
        competencies: competencies
          .filter((c) => c.name.trim())
          .map((c) => ({ ...c, name: c.name.trim(), weight: Number(c.weight) || 0 })),
        rank_by_suitability: rankDefault,
      });
      setSaved(true);
    } catch {
      /* surfaced below via update.error */
    }
  };

  const setComp = (i: number, patch: Partial<Competency>) =>
    setCompetencies((list) => list.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const totalWeight =
    (Number(wSkills) || 0) + (Number(wDesirable) || 0) + competencies.reduce((a, c) => a + (Number(c.weight) || 0), 0);

  const error = update.error instanceof ApiError ? update.error.detail : update.error?.message;

  return (
    <div className="bg-card border border-border rounded-lg p-4 sm:p-6 shadow-sm flex flex-col gap-4 max-w-4xl">
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="w-4.5 h-4.5 text-primary" />
        <h2 className="font-semibold text-base text-foreground">Screening rules for this post</h2>
      </div>
      <p className="text-sm text-muted font-normal leading-relaxed">
        <span className="font-semibold text-foreground">Must-have</span> criteria decide eligibility: failing one means
        not eligible. Everything else is <span className="font-semibold text-foreground">soft</span> — skills and
        desirable items are scored and used to rank candidates within each result group. Experience is not scored:
        meeting the requirement is a must-have, and a small shortfall is handled by the tolerance below. Gemini marks
        each criterion from the JD's own wording; change it with the Must-have tick below.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <NumberField
          label="Experience tolerance (years)"
          hint="Short of a must-have experience requirement by up to this much → needs review instead of rejected."
          value={tolerance}
          onChange={setTolerance}
          step="0.5"
        />
        <NumberField
          label="Skills match for “strong candidate” (%)"
          hint="Within the tolerance AND at least this skills match → tagged “Strong candidate, with exception”."
          value={threshold}
          onChange={setThreshold}
        />
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <p className="text-sm font-semibold text-foreground">Scoring marks (total must be 100)</p>
          <span className={`text-sm font-bold tabular-nums ${totalWeight === 100 ? 'text-success' : 'text-danger'}`}>
            {totalWeight} / 100
          </span>
        </div>
        <ul className="flex flex-col divide-y divide-border border border-border rounded-lg">
          <MarksRow name="Technical skills" value={wSkills} onValue={setWSkills} />
          <MarksRow name="Desirable items" value={wDesirable} onValue={setWDesirable} />
          {competencies.map((c, i) => (
            <MarksRow
              key={c.key ?? `new-${i}`}
              name={c.name}
              // A renamed field is scored by its new name alone.
              onName={(name) => setComp(i, { name, description: '' })}
              value={String(c.weight)}
              onValue={(v) => setComp(i, { weight: v === '' ? 0 : Number(v) })}
              onRemove={() => setCompetencies((list) => list.filter((_, j) => j !== i))}
            />
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setCompetencies((list) => [...list, { name: '', description: '', weight: 0 }])}
          className="self-start flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline"
        >
          <Plus className="w-4 h-4" /> Add field
        </button>
      </div>

      <label className="flex items-center gap-2 text-sm font-medium text-foreground">
        <input type="checkbox" checked={rankDefault} onChange={(e) => setRankDefault(e.target.checked)} />
        Show results ranked by suitability score (best first) by default
      </label>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={update.isPending || totalWeight !== 100}
          title={totalWeight !== 100 ? 'Scoring marks must add up to 100' : undefined}
          className="bg-primary text-primary-foreground font-semibold text-sm px-5 py-2.5 rounded-lg flex items-center gap-2 disabled:opacity-50"
        >
          {update.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save rules
        </button>
        {saved && <span className="text-sm font-medium text-success">Saved — applies on the next screening.</span>}
        {error && <span className="text-sm font-medium text-danger">{error}</span>}
      </div>
    </div>
  );
};

export default ScreeningSettingsCard;
