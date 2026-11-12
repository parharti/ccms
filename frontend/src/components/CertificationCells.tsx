import React from 'react';
import { ShieldCheck, ShieldOff } from 'lucide-react';
import type { CVCertification } from '../types';

/**
 * Compact table-cell renderers for the two CV-certification columns that
 * appear next to each candidate (Results page, job-profile candidate list).
 * The same wording is used by the Excel export on the backend, so what HR
 * sees on screen matches what they download.
 *
 *   certifications === null/undefined -> nothing extracted yet: either the
 *     candidate has not been screened, or no readable CV was uploaded.
 *   certifications === []             -> the CV was read and lists none.
 */

interface Props {
  certifications?: CVCertification[] | null;
  screened: boolean;
}

export const CertificatesCell: React.FC<Props> = ({ certifications, screened }) => {
  if (certifications == null) {
    return <span className="text-muted font-normal">{screened ? 'No readable CV' : '—'}</span>;
  }
  if (certifications.length === 0) {
    return <span className="text-muted font-normal">None mentioned in CV</span>;
  }
  return (
    <ul className="flex flex-col gap-0.5 min-w-[180px] max-w-xs">
      {certifications.map((c) => (
        <li key={c.name} className="text-sm text-foreground font-normal leading-snug" title={c.reason || undefined}>
          {c.name}
          {(c.issuer || c.year) && (
            <span className="text-muted"> ({[c.issuer, c.year].filter(Boolean).join(', ')})</span>
          )}
        </li>
      ))}
    </ul>
  );
};
