import React, { useEffect, useState } from 'react';
import { Plus, X } from 'lucide-react';
import type { SkillItem } from '../types';

/** HR's weight for one JD skill. The candidate's mark for that skill
 * (same 1 / related = HR's related mark / none 0) is multiplied by it. */
const SKILL_WEIGHT_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: '1 (full)' },
  { value: 0.5, label: '0.5 (half)' },
  { value: 0, label: '0 (not scored)' },
];

const WeightSelect: React.FC<{ value: number; onChange: (w: number) => void; disabled?: boolean }> = ({
  value,
  onChange,
  disabled,
}) => (
  <select
    value={value}
    onChange={(e) => onChange(Number(e.target.value))}
    disabled={disabled}
    className="bg-card border border-border text-foreground text-sm font-medium p-1.5 rounded-lg disabled:opacity-50"
    title="Weight of this skill in the skills score"
  >
    {SKILL_WEIGHT_OPTIONS.map((o) => (
      <option key={o.value} value={o.value}>
        {o.label}
      </option>
    ))}
  </select>
);

/**
 * Free-text mark (0-1) a RELATED skill earns, e.g. Tableau for Power BI.
 * Saved when the field loses focus or Enter is pressed; out-of-range or
 * non-numeric input is refused with a hint instead of being saved.
 */
const RelatedMarkInput: React.FC<{ value: number; onChange: (m: number) => void; disabled?: boolean }> = ({
  value,
  onChange,
  disabled,
}) => {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const parsed = text.trim() === '' ? NaN : Number(text);
  const valid = Number.isFinite(parsed) && parsed >= 0 && parsed <= 1;
  const commit = () => {
    if (valid && parsed !== value) onChange(parsed);
    if (!valid) setText(String(value));
  };
  return (
    <label className="flex items-center gap-2 flex-wrap text-sm">
      <span className="font-semibold text-foreground">Mark for a related skill</span>
      <input
        type="text"
        inputMode="decimal"
        value={text}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          }
        }}
        className={`bg-card border text-foreground text-sm font-medium p-1.5 rounded-lg w-20 disabled:opacity-50 ${
          valid ? 'border-border' : 'border-danger'
        }`}
        title="Any number from 0 to 1"
      />
      <span className={`text-xs font-normal ${valid ? 'text-muted' : 'text-danger'}`}>
        {valid ? 'Any value from 0 to 1, e.g. 0.2 (a similar tool, like Tableau for Power BI)' : 'Enter a number from 0 to 1'}
      </span>
    </label>
  );
};

/**
 * The skill criterion's individual skills, each with a weight dropdown.
 * `editableNames` adds rename / remove / add (used while editing the
 * criterion); without it only the weights change, saved straight away.
 */
export const SkillItemsEditor: React.FC<{
  items: SkillItem[];
  onChange: (items: SkillItem[]) => void;
  editableNames?: boolean;
  disabled?: boolean;
  /** The related-skill mark (0-1); the input shows only with onRelatedMarkChange. */
  relatedMark?: number | null;
  onRelatedMarkChange?: (mark: number) => void;
}> = ({ items, onChange, editableNames = false, disabled = false, relatedMark, onRelatedMarkChange }) => {
  const [newSkill, setNewSkill] = useState('');

  const setAt = (index: number, patch: Partial<SkillItem>) =>
    onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  const addSkill = () => {
    const name = newSkill.trim();
    if (!name || items.some((i) => i.name.toLowerCase() === name.toLowerCase())) return;
    onChange([...items, { name, weight: 1 }]);
    setNewSkill('');
  };

  const scored = items.filter((i) => i.weight > 0);
  const outOf = scored.reduce((sum, i) => sum + i.weight, 0);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm font-semibold text-foreground">Skills and weights</p>
        <p className="text-xs text-muted font-normal">
          Same skill = 1 mark · related skill = {relatedMark ?? 0.5} · none = 0, multiplied by the weight. Max
          score: {outOf}
        </p>
      </div>
      {onRelatedMarkChange && (
        <RelatedMarkInput value={relatedMark ?? 0.5} onChange={onRelatedMarkChange} disabled={disabled} />
      )}
      {items.length === 0 && <p className="text-sm text-muted font-normal">No skills listed yet.</p>}
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {items.map((item, i) => (
          <li
            key={`${i}-${item.name}`}
            className={`flex items-center gap-2 border border-border rounded-lg px-3 py-2 ${item.weight === 0 ? 'opacity-60' : ''}`}
          >
            {editableNames ? (
              <input
                value={item.name}
                onChange={(e) => setAt(i, { name: e.target.value })}
                className="flex-1 min-w-0 bg-accent/40 border border-border text-foreground text-sm font-medium p-1.5 rounded-lg"
              />
            ) : (
              <span className="flex-1 min-w-0 text-sm font-medium text-foreground truncate" title={item.name}>
                {item.name}
              </span>
            )}
            <WeightSelect value={item.weight} onChange={(w) => setAt(i, { weight: w })} disabled={disabled} />
            {editableNames && (
              <button
                type="button"
                onClick={() => onChange(items.filter((_, j) => j !== i))}
                className="text-muted hover:text-danger"
                title="Remove this skill"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {editableNames && (
        <div className="flex items-center gap-2">
          <input
            value={newSkill}
            onChange={(e) => setNewSkill(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addSkill();
              }
            }}
            placeholder="Add a skill, e.g. SQL"
            className="bg-card border border-border text-foreground text-sm font-normal p-2 rounded-lg w-64"
          />
          <button
            type="button"
            onClick={addSkill}
            className="text-sm font-semibold text-primary flex items-center gap-1 px-3 py-2 rounded-lg border border-border hover:border-primary/40"
          >
            <Plus className="w-4 h-4" /> Add skill
          </button>
        </div>
      )}
    </div>
  );
};
