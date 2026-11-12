/**
 * Organisation branding, configurable per deployment (see .env.example):
 *   VITE_ORG_NAME  -- shown in the sidebar and login screen (default "DIC")
 *   VITE_ORG_LOGO  -- optional logo path/URL; without one, a text mark is shown
 */
const env = (import.meta as any).env ?? {};

export const ORG_NAME: string = env.VITE_ORG_NAME || 'DIC';
export const ORG_LOGO: string | undefined = env.VITE_ORG_LOGO || undefined;
