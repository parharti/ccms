/**
 * Types mirroring the FastAPI backend's Pydantic schemas 1:1
 * (see backend/app/schemas/*.py). Kept close to the wire shape rather
 * than IHMCL's original mock shape, since this app now talks to the
 * real screening engine instead of client-side mock data.
 */

export interface HRUser {
  id: string;
  email: string;
}

// ---- Job Profiles / Criteria ----

/** One JD skill, marked on its own. weight: 1, 0.5 or 0 (0 = shown, not scored). */
export interface SkillItem {
  name: string;
  weight: number;
}

export interface Criterion {
  id: string;
  type: 'age' | 'education' | 'experience' | 'skill' | 'other' | string;
  description: string;
  is_essential: boolean;
  display_order: number;
  /** Skill criteria only: minimum match % required when essential. */
  required_match_percentage?: number | null;
  /** Skill criteria only: the skills marked one by one, with HR's weights. */
  skill_items?: SkillItem[] | null;
  /** Skill criteria only: the mark (0-1) a related skill earns; 0.5 by default. */
  related_mark?: number | null;
}

export interface AgeRelaxationRule {
  id: string;
  raw_category: string;
  normalized_category: string;
  relaxation_text: string;
}

export interface JobProfile {
  id: string;
  title: string;
  method_of_recruitment?: string | null;
  pay_scale?: string | null;
  base_age_min?: number | null;
  base_age_max?: number | null;
  /** Misses an essential experience criterion by no more than this many years -> needs review, not rejection. */
  experience_tolerance_years?: number;
  /** ...when the skills match is at least this % (tagged "strong candidate, with exception"). */
  exception_skills_threshold?: number;
  /** Weights of the suitability score used for ranking. */
  weight_skills?: number;
  weight_experience?: number;
  weight_desirable?: number;
  /** "Close miss" tag: a Not eligible candidate scoring at least this % in a section. null = that check is off. */
  close_miss_skills_min?: number | null;
  close_miss_experience_min?: number | null;
  close_miss_desirable_min?: number | null;
  /** Results open ranked by suitability score when true. */
  rank_by_suitability?: boolean;
  criteria: Criterion[];
  age_relaxation_rules: AgeRelaxationRule[];
}

export interface JDUploadResponse {
  jd_upload_id: string;
  filename: string;
  parse_confidence: string;
  ambiguity_notes: string;
  post_count: number;
  validation_warnings: string[];
  is_duplicate: boolean;
  duplicate_message?: string | null;
  job_profiles: JobProfile[];
}

export interface CriterionCreate {
  type: string;
  description: string;
  is_essential?: boolean;
  display_order?: number | null;
  required_match_percentage?: number | null;
  skill_items?: SkillItem[] | null;
  related_mark?: number | null;
}

export type CriterionUpdate = Partial<CriterionCreate>;

// ---- Candidates ----

export interface CandidateDocument {
  id: string;
  document_type: string;
  original_filename: string;
}

export type CandidateStatus = 'eligible' | 'not_eligible' | 'needs_review' | 'not_evaluated';

/** One certificate/course/licence listed in the candidate's CV, extracted by Gemini during screening. */
export interface CVCertification {
  name: string;
  issuer?: string | null;
  year?: string | null;
  is_cyber_security: boolean;
  reason?: string | null;
}

export interface Candidate {
  id: string;
  external_id: string;
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  dob?: string | null;
  gender?: string | null;
  raw_category?: string | null;
  normalized_category?: string | null;
  ingestion_status: string;
  /** Roster-only uploads: no_link / pending / fetching / fetched / failed. null for ZIP uploads. */
  resume_fetch_status?: string | null;
  resume_fetch_error?: string | null;
  /** strong_exception / awaiting_resume / resume_unavailable (needs review) or close_miss (not eligible, but scores well in a section). */
  review_tag?: string | null;
  review_note?: string | null;
  /** 0-100 weighted score over the soft sections; ranking sorts by it. */
  suitability_score?: number | null;
  computed_status?: CandidateStatus | null;
  status: CandidateStatus;
  status_overridden: boolean;
  /** The batch screening run this candidate was last evaluated in. */
  last_screening_run_id?: string | null;
  /** Result produced under criteria that have since been edited; null = not screened yet. */
  results_outdated?: boolean | null;
  /** null = not extracted yet (not screened, or no readable CV); [] = CV lists no certificates. */
  cv_certifications?: CVCertification[] | null;
  /** true when at least one CV certificate is cyber-security related; null mirrors cv_certifications. */
  has_cyber_security_certification?: boolean | null;
  /** Overall skills-match % from screening; null until screened. */
  skill_match_percentage?: number | null;
  /** Government Relevant Experience tag (never on a not-eligible candidate). */
  gov_tag?: boolean;
  gov_experience?: GovExperience | null;
  documents: CandidateDocument[];
}

export interface GovJob {
  organisation: string;
  designation?: string | null;
  period?: string | null;
  is_government: boolean;
  role_relevant: boolean;
  reason?: string | null;
}

export interface GovExperience {
  jobs: GovJob[];
}

export interface ResumeFetchStatus {
  pending: number;
  fetching: number;
  fetched: number;
  failed: number;
  no_link: number;
  /** Shortlisted (eligible / needs review) candidates whose resume is still to be fetched. */
  shortlisted_waiting: number;
}

export interface CandidateUploadSummary {
  job_profile_id: string;
  total_candidates_found: number;
  replaced_candidates?: number;
  documents_complete: number;
  documents_incomplete: number;
  no_documents_found: number;
  excel_row_not_found: number;
  corrupt_zip: number;
  candidates: Candidate[];
}

// ---- Screening / Review ----

export interface CriterionEvaluation {
  id: string;
  criterion_id: string;
  result: 'pass' | 'fail' | 'needs_review' | string;
  match_percentage?: number | null;
  citation_document?: string | null;
  citation_page?: number | null;
  reasoning?: string | null;
}

export interface CandidateEvaluationResult {
  candidate_id: string;
  ingestion_status: string;
  status: CandidateStatus;
  skipped: boolean;
  skip_reason?: string | null;
  cv_certifications?: CVCertification[] | null;
  has_cyber_security_certification?: boolean | null;
  evaluations: CriterionEvaluation[];
}

export interface ScreeningRun {
  id: string;
  job_profile_id: string;
  total_candidates: number;
  processed_count: number;
  failed_count: number;
  status: 'running' | 'stopping' | 'completed' | 'stopped' | 'failed' | string;
  error_message?: string | null;
  started_at: string;
  completed_at?: string | null;
  /** Candidates whose LATEST screening is this run (runs-list endpoint only). */
  current_candidates?: number | null;
  /** Stopped/crashed runs: candidates it never reached (what Continue screens). */
  remaining_candidates?: number | null;
}

export interface CriterionEvaluationDetail {
  criterion_id: string;
  criterion_type: string;
  criterion_description: string;
  is_essential: boolean;
  result: string;
  match_percentage?: number | null;
  /** Skill criteria only: how each JD skill was marked. */
  skill_marks?: SkillMark[] | null;
  citation_document?: string | null;
  citation_page?: number | null;
  reasoning?: string | null;
}

/** level: same (1) / related (0.5) / none (0); points = mark x weight. */
export interface SkillMark {
  skill: string;
  weight: number;
  level: 'same' | 'related' | 'none';
  candidate_skill?: string | null;
  source?: 'sheet' | 'resume' | 'both' | null;
  mark: number;
  points: number;
  reason?: string | null;
}

export interface ReviewDocument {
  id: string;
  document_type: string;
  original_filename: string;
}

export interface ConsistencyCheck {
  item: string;
  roster?: string | null;
  resume?: string | null;
  verdict: 'consistent' | 'inconsistent' | 'unverified';
  note?: string | null;
}

/** Roster-vs-resume check on experience + must-have items (informational). */
export interface ResumeConsistency {
  overall: 'consistent' | 'inconsistent' | 'unverified';
  checks: ConsistencyCheck[];
}

export interface CandidateReviewDetail {
  candidate_id: string;
  external_id?: string | null;
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  dob?: string | null;
  gender?: string | null;
  raw_category?: string | null;
  normalized_category?: string | null;
  ingestion_status: string;
  computed_status?: CandidateStatus | null;
  status: CandidateStatus;
  status_overridden: boolean;
  override_reason?: string | null;
  overridden_by?: string | null;
  overridden_at?: string | null;
  cv_certifications?: CVCertification[] | null;
  has_cyber_security_certification?: boolean | null;
  resume_consistency?: ResumeConsistency | null;
  review_tag?: string | null;
  review_note?: string | null;
  suitability_score?: number | null;
  gov_tag?: boolean;
  gov_experience?: GovExperience | null;
  evaluations: CriterionEvaluationDetail[];
  documents?: ReviewDocument[];
}

export interface OverrideRequest {
  new_status: 'eligible' | 'not_eligible' | 'needs_review';
  reason?: string;
}

// ---- Results ----

export interface ResultsSummary {
  total: number;
  eligible: number;
  /** Needs-review candidates tagged strong_exception (not counted in needs_review). */
  eligible_with_exception: number;
  not_eligible: number;
  needs_review: number;
  not_evaluated: number;
  /** Candidates with the Government Relevant Experience tag. */
  gov_tagged: number;
}

export interface ResultsResponse {
  summary: ResultsSummary;
  candidates: Candidate[];
}

// ---- Dashboard ----

export interface RecentJDUpload {
  id: string;
  filename: string;
  uploaded_at: string;
  post_count: number;
}

export interface RecentScreeningRun {
  id: string;
  job_profile_id: string;
  job_profile_title: string;
  status: string;
  total_candidates: number;
  processed_count: number;
  failed_count: number;
  started_at: string;
  completed_at?: string | null;
}

export interface DashboardSummary {
  total_job_profiles: number;
  total_candidates: number;
  candidates_by_status: Record<string, number>;
  recent_jd_uploads: RecentJDUpload[];
  recent_screening_runs: RecentScreeningRun[];
}


// ---- Department templates (how a department's candidate sheet is laid out) ----

export type EvidenceMode = 'documents_primary' | 'declared_primary';

export const TEMPLATE_FIELDS = [
  { key: 'external_id', label: 'Candidate ID (matches the folder name)', required: true },
  { key: 'name', label: 'Name', required: false },
  { key: 'email', label: 'Email', required: false },
  { key: 'phone', label: 'Phone', required: false },
  { key: 'dob', label: 'Date of birth', required: false },
  { key: 'gender', label: 'Gender', required: false },
  { key: 'category', label: 'Category', required: false },
] as const;

export interface DepartmentTemplateInput {
  name: string;
  description?: string | null;
  field_map: Record<string, string | null>;
  header_row?: number | null;
  document_columns: Record<string, string>;
  resume_filename_patterns: string[];
  evidence_mode: EvidenceMode;
}

export interface DepartmentTemplate extends DepartmentTemplateInput {
  id: string;
}

export interface SheetInspection {
  header_row: number;
  headers: string[];
  sample_rows: Record<string, string | null>[];
}
