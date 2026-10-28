import type { Condition, Folio, RichValue, ReviewRecord } from "./types";

export const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
export const percent = (value: unknown, digits = 1) =>
  finite(value) ? `${(value * 100).toFixed(digits)}%` : "Not available";
export const effect = (value: unknown, digits = 2) =>
  finite(value)
    ? `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value * 100).toFixed(digits)}`
    : "—";
export const integer = (value: unknown) =>
  finite(value) ? new Intl.NumberFormat("en").format(value) : "Not reported";
export const hashShort = (value?: string) =>
  value ? `${value.slice(0, 10)}…${value.slice(-6)}` : "Hash not available";
export const words = (value?: string) =>
  (value ?? "").replaceAll("_", " ").replace(/\b\w/g, (s) => s.toUpperCase());
export const date = (value?: string) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Intl.DateTimeFormat("en", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      }).format(new Date(value))
    : "Not recorded";
export const dateTime = (value?: string) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Intl.DateTimeFormat("en", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))
    : "Not recorded";
export const time = (value?: string) =>
  value && !Number.isNaN(Date.parse(value))
    ? new Intl.DateTimeFormat("en", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(value))
    : "Not recorded";
export const bytes = (value?: number) =>
  finite(value)
    ? value >= 1024 * 1024
      ? `${(value / (1024 * 1024)).toFixed(1)} MB`
      : value >= 1024
        ? `${(value / 1024).toFixed(1)} KB`
        : `${value} B`
    : "Size not reported";
export const reviewName = (review?: ReviewRecord | null) =>
  review?.reviewer_name ?? review?.reviewer ?? review?.name ?? "Local operator";
export const reviewNote = (review?: ReviewRecord | null) =>
  review?.review_note ?? review?.note ?? review?.reason;
export const reviewDate = (review?: ReviewRecord | null) =>
  review?.reviewed_at ??
  review?.approved_at ??
  review?.created_at ??
  review?.timestamp;

export function textValue(value?: RichValue | unknown): string {
  if (value === null || value === undefined || value === "")
    return "Not specified";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  if (Array.isArray(value)) return value.map(textValue).join(" · ");
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${words(key)}: ${textValue(item)}`)
    .join("\n");
}
export function safeHref(value?: string): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}
export const conditionLabel = (folio: Folio, id: string) =>
  folio.contract?.allowed_conditions?.find((condition) => condition.id === id)
    ?.label ??
  folio.observations?.find((observation) => observation.condition_id === id)
    ?.condition_label ??
  words(id);
export const activeConditionIds = (folio: Folio) =>
  (
    folio.exploration_plan?.conditions ??
    folio.contract?.active_conditions ??
    []
  ).map((condition) =>
    typeof condition === "string" ? condition : condition.id,
  );
export const scopeLabel = (scope?: string) =>
  scope === "in_scope"
    ? "In registered scope"
    : scope === "applicability"
      ? "Applicability test"
      : scope
        ? words(scope)
        : "Scope not recorded";
export const isActive = (folio: Folio) =>
  ["running", "cancel_requested", "queued", "provisioning"].includes(
    folio.status,
  ) ||
  (!!folio.run &&
    ["running", "queued", "cancel_requested", "resuming"].includes(
      folio.run.status,
    ));
export const reproductionAccepted = (folio: Folio) =>
  folio.reproduction_accepted ??
  ([
    "reproduced",
    "evidence_review",
    "explored",
    "confirmation_locked",
    "confirmation_ready",
    "review_ready",
    "complete",
  ].includes(folio.status) ||
    Boolean(
      folio.evidence_change ||
      folio.registration ||
      folio.verification ||
      folio.observations?.some(
        (observation) => observation.phase === "discovery",
      ),
    ));
export const conditions = (folio: Folio): Condition[] =>
  folio.contract?.allowed_conditions ?? [];
export const outcomeLabel = (outcome?: string | null) =>
  ({
    supported_in_tested_scope: "Supported in tested scope",
    boundary_identified: "Applicability boundary",
    evidence_against_registered_claim: "Evidence against claim",
    inconclusive: "Inconclusive",
    reproduction_failed: "Reproduction unresolved",
    not_testable: "Not testable",
  })[outcome ?? ""] ?? (outcome ? words(outcome) : "Awaiting evidence");
