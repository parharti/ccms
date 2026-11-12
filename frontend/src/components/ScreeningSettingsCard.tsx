import React, { useEffect, useState } from 'react';
import { Loader2, Save, SlidersHorizontal } from 'lucide-react';
import { useUpdateProfileSettings } from '../hooks/useJobProfile';
import { ApiError } from '../context/AuthContext';
import type { JobProfile } from '../types';

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
  const [wSkills, setWSkills] = useState('50');
  const [wExperience, setWExperience] = useState('30');
  const [wDesirable, setWDesirable] = useState('20');
  const [rankDefault, setRankDefault] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setTolerance(String(profile.experience_tolerance_years ?? 2));
    setThreshold(String(profile.exception_skills_threshold ?? 80));
    setWSkills(String(profile.weight_skills ?? 50));
    setWExperience(String(profile.weight_experience ?? 30));
    setWDesirable(String(profile.weight_desirable ?? 20));
    setRankDefault(profile.rank_by_suitability ?? true);
  }, [
    profile.experience_tolerance_years,
    profile.exception_skills_threshold,
    profile.weight_skills,
    profile.weight_experience,
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
        weight_experience: Number(wExperience),
        weight_desirable: Number(wDesirable),
        rank_by_suitability: rankDefault,
      });
      setSaved(true);
    } catch {
      /* surfaced below via update.error */
    }
  };

  const error = update.error instanceof ApiError ? update.error.detail : update.error?.message;

  return (
    <div className="bg-card border border-border rounded-lg p-6 shadow-sm flex flex-col gap-4 max-w-4xl">
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="w-4.5 h-4.5 text-primary" />
        <h2 className="font-semibold text-base text-foreground">Screening rules for this post</h2>
      </div>
      <p className="text-sm text-muted font-normal leading-relaxed">
        <span className="font-semibold text-foreground">Must-have</span> criteria decide eligibility: failing one means
        not eligible. Everything else is <span className="font-semibold text-foreground">soft</span> — skills,
        experience depth and desirable items are scored and used to rank eligible candidates. Gemini marks each
        criterion from the JD's own wording; change it with the Must-have tick below.
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

      <div>
        <p className="text-sm font-semibold text-foreground mb-2">Ranking weights (suitability score)</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <NumberField label="Skills" hint="Skills match %" value={wSkills} onChange={setWSkills} />
          <NumberField label="Experience" hint="Experience match %" value={wExperience} onChange={setWExperience} />
          <NumberField label="Desirable items" hint="Preferred degrees etc." value={wDesirable} onChange={setWDesirable} />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm font-medium text-foreground">
        <input type="checkbox" checked={rankDefault} onChange={(e) => setRankDefault(e.target.checked)} />
        Show results ranked by suitability score (best first) by default
      </label>

      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={update.isPending}
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
