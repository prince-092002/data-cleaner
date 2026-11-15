// Mirrors docs/CONTRACT.md (sections 2.4, 3, 4, 5, 7, 8). Do not add logic here.

export type FileType = 'csv' | 'xlsx'
export type Mode = 'auto' | 'suggest' | 'flag'
export type Severity = 'high' | 'medium' | 'low'

export interface ProposalSample {
  row_id: number | null
  before: string | null
  after: string | null
}

/** A value a rule saw but did not change, and why. */
export interface LeftAlone {
  value: string
  count: number
  reason: string
}

export interface Proposal {
  id: string
  rule_id: string
  rule_version: string
  column: string | null
  mode: Mode
  severity: Severity
  is_destructive: boolean
  confidence: number | null
  title: string
  description: string
  rows_affected: number
  params: Record<string, unknown>
  editable_params: string[]
  samples: ProposalSample[]
  left_alone: LeftAlone[]
}

export interface QualityScore {
  overall: number
  completeness: number
  validity: number
  consistency: number
  uniqueness: number
  conformity: number
}

export interface ColumnQuality {
  score: number
  completeness: number
  validity: number
  consistency: number
  uniqueness: number
  conformity: number
}

export type InferredType =
  | 'integer'
  | 'decimal'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'category'
  | 'text'
  | 'id'
  | 'empty'

export type IssueCode =
  | 'missing_values'
  | 'null_tokens'
  | 'whitespace'
  | 'hidden_characters'
  | 'encoding_damage'
  | 'mixed_types'
  | 'numeric_as_text'
  | 'mixed_date_formats'
  | 'ambiguous_dates'
  | 'inconsistent_booleans'
  | 'inconsistent_categories'
  | 'outliers'
  | 'duplicate_keys'
  | 'messy_header'
  | 'empty_column'

export interface ColumnIssue {
  code: IssueCode
  severity: Severity
  message: string
  count: number
}

export interface ColumnProfile {
  name: string
  source_name: string
  position: number
  inferred_type: InferredType
  type_confidence: number
  row_count: number
  null_count: number
  null_pct: number
  distinct_count: number
  distinct_pct: number
  is_key_candidate: boolean
  min: string | null
  max: string | null
  mean: number | null
  median: number | null
  min_length: number | null
  max_length: number | null
  top_values: { value: string; count: number }[]
  samples: string[]
  format_patterns: { pattern: string; count: number }[]
  issues: ColumnIssue[]
  quality: ColumnQuality
}

export interface SourceInfo {
  filename: string
  file_type: FileType
  encoding: string | null
  delimiter: string | null
  sheet: string | null
  header_row: number
}

export interface DatasetProfile {
  schema_version: string
  source: SourceInfo
  row_count: number
  column_count: number
  duplicate_row_count: number
  empty_row_count: number
  quality: QualityScore
  columns: ColumnProfile[]
  proposals: Proposal[]
}

/** GET /api/datasets/{id}/profile */
export interface ProfileResponse extends DatasetProfile {
  dataset_id: string
}

export interface EditedProposal {
  id: string
  params: Record<string, unknown>
}

export interface Decisions {
  approved: string[]
  rejected: string[]
  edited: EditedProposal[]
}

export interface ColumnScoreChange {
  name: string
  before: ColumnQuality | null
  after: ColumnQuality | null
}

export type ChangeAction = 'auto' | 'approved'
export type ChangeType =
  | 'cell'
  | 'row_removed'
  | 'column_removed'
  | 'header_renamed'
  | 'column_added'

export interface RuleChangeSummary {
  rule_id: string
  action: ChangeAction
  changes: number
  columns: string[]
}

export interface ChangeSummary {
  total_changes: number
  cells_changed: number
  rows_removed: number
  columns_removed: number
  columns_added: number
  rows_before: number
  rows_after: number
  columns_before: number
  columns_after: number
  by_rule: RuleChangeSummary[]
}

export interface ChangeRecord {
  run_id: string
  rule_id: string
  rule_version: string
  row_id: number | null
  column: string | null
  change_type: ChangeType
  old_value: string | null
  new_value: string | null
  action: ChangeAction
  timestamp: string
  reason?: string | null
}

export interface ChangesPage {
  total: number
  limit: number
  offset: number
  items: ChangeRecord[]
}

export type DownloadName =
  | 'clean.csv'
  | 'clean.xlsx'
  | 'report.html'
  | 'recipe.yaml'
  | 'changelog.csv'

export interface ResultsResponse {
  dataset_id: string
  run_id: string
  before: QualityScore
  after: QualityScore
  columns: ColumnScoreChange[]
  summary: ChangeSummary
  changes: ChangesPage
  downloads: DownloadName[]
  warnings: string[]
}

/** Query params of GET /api/datasets/{id}/results (limit default 100, max 500). */
export interface ResultsQuery {
  limit?: number
  offset?: number
  rule_id?: string
  column?: string
  action?: ChangeAction
  change_type?: ChangeType
}

export interface SheetInfo {
  name: string | null
  row_count_estimate: number
  detected_header_row: number
  preview: string[][]
}

export interface UploadResponse {
  dataset_id: string
  filename: string
  file_type: FileType
  size_bytes: number
  expires_at: string
  sheets: SheetInfo[]
}

export interface ProfileRequest {
  sheet?: string | null
  header_row?: number
}

export interface JobCreated {
  job_id: string
}

export type JobType = 'profile' | 'clean'
export type JobState = 'queued' | 'running' | 'done' | 'failed'

export interface JobError {
  code: string
  message: string
}

export interface JobStatus {
  job_id: string
  dataset_id: string
  type: JobType
  status: JobState
  progress_pct: number
  current_step: string
  error: JobError | null
  created_at: string
  updated_at: string
}

export type ApiErrorCode =
  | 'invalid_request'
  | 'not_found'
  | 'not_ready'
  | 'file_too_large'
  | 'unsupported_file_type'
  | 'unreadable_file'
  | 'internal_error'

export interface ApiErrorBody {
  error: { code: string; message: string }
}
