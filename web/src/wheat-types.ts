/** Public, released wheat evidence only. Boxes are xywh in original image pixels. */
export type WheatBox = [number, number, number, number];
export interface WheatTarget {
  id: string;
  bbox: WheatBox;
}
export interface WheatPrediction extends WheatTarget {
  score: number;
  match_kind: "matched" | "duplicate" | "false_positive";
  target_id?: string | null;
}
export interface WheatAsset {
  id: string;
  url: string;
  width: number;
  height: number;
  sha256: string;
  license: string;
  attribution: string;
  source_url: string;
  session_id: string;
  split: string;
  ground_truth_released: boolean;
  targets: WheatTarget[];
  selection_rule?: string;
}
export interface WheatMetrics {
  target_count: number;
  predicted_count: number;
  absolute_count_error: number;
  relative_count_error: number | null;
  localization_metric: string;
  localization_value: number;
  bytes: number;
  wall_ms: number;
  peak_rss_mb?: number | null;
  matched_count?: number;
  duplicate_count?: number;
  false_positive_count?: number;
}
export interface WheatAggregate {
  seeds?: number[];
  n_images: number;
  n_sessions: number;
  count_mae: number;
  count_bias: number;
  localization_value: number;
  total_upload_bytes: number;
  total_wall_ms: number;
}
export interface WheatCell {
  seed?: number;
  id: string;
  label: string;
  recipe_id: string;
  retained_width: number;
  width?: number;
  status: "unrun" | "running" | "succeeded" | "failed" | "disabled";
  enabled: boolean;
  disabled_reason?: string;
  transform: {
    url: string;
    width: number;
    height: number;
    sha256: string;
    resampler: string;
    encoding: string;
    coordinate_mapping: string;
  } | null;
  predictions: WheatPrediction[];
  missed_target_ids: string[];
  metrics: WheatMetrics | null;
  aggregate: WheatAggregate | null;
  receipt_id?: string | null;
  limitations?: string[];
  error?: string | null;
  score_threshold?: number;
  iou_threshold?: number;
}
export interface WheatRecipe {
  id: string;
  label: string;
  description?: string;
  family?: string;
  attribution_url?: string;
  parameters?: Record<string, unknown>;
}
export interface WheatSourceField {
  key: string;
  label: string;
  candidates: {
    value: unknown;
    source_title: string;
    url: string;
    locator?: string;
  }[];
  status: "source_supported" | "reviewer_chosen" | "unresolved";
  selected_value?: unknown;
  reason?: string;
  critical?: boolean;
}
export interface WheatReceipt {
  id: string;
  kind?: string;
  provider?: string;
  model?: string | null;
  purpose?: string;
  status: string;
  started_at?: string;
  elapsed_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  request_id?: string | null;
  error?: string | null;
  url?: string;
  [key: string]: unknown;
}
export interface WheatArtifact {
  id?: string;
  label?: string;
  name?: string;
  url: string;
  sha256?: string;
  kind?: string;
}
export interface WheatStudy {
  schema_version: string;
  id: string;
  revision: number;
  title: string;
  experiment_kind: string;
  status: string;
  scope?: string;
  limitations: string[];
  capabilities: string[];
  asset: WheatAsset | null;
  cells: WheatCell[];
  recipes: WheatRecipe[];
  source_fields: WheatSourceField[];
  source_readiness?: {
    status: string;
    available_images: number;
    required_images: number;
    missing_images: number;
    detail: string;
  } | null;
  source_compilation?: {
    status: string;
    method?: string;
    method_label?: string;
    packet_sha256?: string;
    fields: {
      field: string;
      source_id: string;
      value: string;
      locator: string;
      status: "source_supported" | "reviewer_chosen" | "unresolved";
      url?: string;
    }[];
    conflict_resolution: string;
    unresolved?: string[];
    limitation?: string;
    receipt_id?: string | null;
  } | null;
  training: {
    status: string;
    detector: string;
    device: string;
    checkpoint_sha256?: string | null;
    checkpoint_set_sha256?: string | null;
    seeds?: number[];
    epochs?: number | null;
    receipt_id?: string | null;
    detail?: string;
  };
  run: {
    status: string;
    action: string;
    checkpoint: string;
    error?: string | null;
    can_resume: boolean;
  } | null;
  evidence_change: {
    status: string;
    before: string[];
    after: string[];
    source?: { title: string; url: string; excerpt?: string } | null;
    assumption: string;
    explanation: string;
    receipt_id?: string | null;
    decision?: unknown;
  } | null;
  registration: {
    status: string;
    sha256?: string | null;
    registered_at?: string | null;
    cell_id?: string | null;
    configuration?: unknown;
    requirement?: unknown;
    review_status: string;
    detail?: string;
  };
  custody: {
    status: string;
    dataset_fingerprint?: string | null;
    split_manifest_sha256?: string | null;
    exposure_status: string;
    external_custodian?: string | null;
    public_benchmark_caveat: string;
    detail?: string;
  };
  planning: {
    status: string;
    proposal?: string | null;
    next_cell_id?: string | null;
    rationale?: string;
    receipt_id?: string | null;
    competing_predictions?: { explanation: string; prediction: string }[];
    observed_result?: string | null;
  };
  decision: {
    status: string;
    label: string;
    reason: string;
    limitations: string[];
  };
  receipts: WheatReceipt[];
  artifacts: WheatArtifact[];
  export_url?: string | null;
  updated_at?: string;
}
