export type Stage =
  "contract" | "reproduction" | "challenge" | "confirmation" | "folio";
export type InspectorTab =
  "source" | "data" | "computation" | "review" | "activity";
export type AdapterId = "occupancy" | "synthetic";
export type Scope = "in_scope" | "applicability" | string;
export type RichValue =
  string | number | boolean | null | Record<string, unknown> | unknown[];

export interface Condition {
  id: string;
  label: string;
  feature?: string;
  rate?: number | string;
  scope: Scope;
  description?: string;
}
export interface ReviewRecord {
  reviewer_name?: string;
  reviewer?: string;
  name?: string;
  review_note?: string;
  note?: string;
  reason?: string;
  reviewed_at?: string;
  approved_at?: string;
  created_at?: string;
  timestamp?: string;
  [key: string]: unknown;
}
export interface Contract {
  schema_version?: string;
  revision: number;
  sha256?: string;
  claim: string;
  population?: RichValue;
  candidate?: { name: string; parameters?: RichValue };
  baseline?: { name: string; parameters?: RichValue };
  metric?: string;
  practical_delta: number;
  alpha?: number;
  analysis?: RichValue;
  split?: RichValue;
  preprocessing?: RichValue;
  seeds?: number[];
  allowed_conditions?: Condition[];
  active_conditions?: (string | Condition)[];
  scope?: RichValue;
  approval?: ReviewRecord | null;
  model_proposal?: RichValue;
  locked: boolean;
  [key: string]: unknown;
}
export interface Source {
  title: string;
  url?: string;
  license?: string;
  attribution?: string;
  description?: string;
  sha256?: string;
  files?: { name: string; sha256?: string; rows?: number; split?: string }[];
  audit?: RichValue;
  kind?: string;
  source_span?: RichValue;
}
export interface Run {
  id: string;
  action: string;
  status: string;
  started_at?: string;
  updated_at?: string;
  heartbeat_at?: string;
  checkpoint?: RichValue;
  completed_units?: number | null;
  total_units?: number | null;
  unit_label?: string;
  attempt?: number;
  error?: string | { message?: string; code?: string } | null;
  can_resume?: boolean;
}
export interface EvidenceChange {
  id: string;
  status: "proposed" | "accepted" | "rejected" | "context_only";
  query?: string;
  queried_at?: string;
  source?: { title: string; url?: string; excerpt?: string };
  assumption?: string;
  before?: string[];
  after?: string[];
  explanation?: string;
  decision?: ReviewRecord | string | null;
  receipt_id?: string;
}
export interface Observation {
  id: string;
  phase: "reproduction" | "discovery" | "confirmation";
  condition_id: string;
  condition_label?: string;
  scope?: Scope;
  candidate: number | null;
  baseline: number | null;
  effect: number | null;
  ci_low: number | null;
  ci_high: number | null;
  blocks?: number | null;
  total_blocks?: number | null;
  rows?: number | null;
  analyzed_rows?: number | null;
  seeds?: number[] | number;
  seed_effects?: (
    number | { seed?: number; effect?: number; [key: string]: unknown }
  )[];
  unit?: string;
  interval_method?: string;
  warning?: string | string[] | null;
  artifact_sha256?: string;
  [key: string]: unknown;
}
export interface Proposal {
  condition_id: string;
  rank: number;
  rationale: string;
  expected_information?: string;
  scope?: Scope;
}
export interface Registration {
  condition_id: string;
  registered_at: string;
  sha256?: string;
  reviewer_name?: string;
  analysis?: RichValue;
  holdout_status?: string;
  prior_folio_id?: string | null;
}
export interface Verification {
  status: "verified" | "rejected";
  sha256?: string;
  checks: { name: string; passed: boolean; detail?: string }[];
  metrics?: RichValue;
  decision?: RichValue;
  method?: RichValue;
  independence?: RichValue;
  artifact_sha256?: string;
}
export interface Conclusion {
  outcome: string;
  title: string;
  statement: string;
  scope?: RichValue;
  limitations?: string[];
  references?: string[];
  review?: ReviewRecord | null;
}
export interface Receipt {
  id: string;
  kind: string;
  provider?: string;
  model?: string;
  status: string;
  request_id?: string;
  started_at?: string;
  elapsed_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  estimated_cost_usd?: number | null;
  error?: string | null;
  purpose?: string;
}
export interface FolioEvent {
  seq: number;
  type: string;
  message: string;
  created_at: string;
  run_id?: string;
}
export interface Artifact {
  sha256: string;
  name: string;
  media_type: string;
  kind?: string;
  bytes?: number;
}
export interface FolioSummary {
  id: string;
  adapter_id: AdapterId;
  title: string;
  claim: string;
  case_kind?: "authored_public_data" | "controlled_synthetic";
  created_at?: string;
  updated_at?: string;
  stage: Stage;
  status: string;
  revision?: number;
  conclusion?: Conclusion | null;
  outcome?: string | null;
  [key: string]: unknown;
}
export interface Folio extends FolioSummary {
  revision: number;
  source: Source | null;
  contract: Contract | null;
  run: Run | null;
  evidence_change: EvidenceChange | null;
  observations: Observation[];
  proposals: Proposal[];
  registration: Registration | null;
  verification: Verification | null;
  conclusion: Conclusion | null;
  receipts: Receipt[];
  events: FolioEvent[];
  artifacts: Artifact[];
  limitations: string[];
  exploration_plan?: {
    conditions: (string | Condition)[];
    review?: ReviewRecord;
    contract_sha256?: string;
    sha256?: string;
  } | null;
  planner_error?: string | null;
  reproduction_review?: ReviewRecord | null;
  reproduction_accepted?: boolean;
  exploration_complete?: boolean;
  prediction_manifest?: RichValue;
}
export type Action =
  | "propose_contract"
  | "update_contract"
  | "lock_contract"
  | "reproduce"
  | "accept_reproduction"
  | "retrieve"
  | "accept_evidence"
  | "reject_evidence"
  | "explore"
  | "register_confirmation"
  | "confirm"
  | "verify"
  | "review_conclusion"
  | "cancel"
  | "resume";
export interface ApiErrorData {
  code: string;
  message: string;
  recoverable?: boolean;
}
export interface Health {
  status?: string;
  [key: string]: unknown;
}
export interface Route {
  folio: string | null;
  stage: Stage;
  inspector: InspectorTab;
  condition: string | null;
}
