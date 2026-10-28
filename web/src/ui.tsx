import { useEffect, useId, useRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CircleAlert,
  ExternalLink,
  Info,
  LoaderCircle,
  Pause,
  Play,
  ShieldCheck,
  X,
} from "lucide-react";
import { artifactUrl } from "./api";
import {
  dateTime,
  finite,
  hashShort,
  isActive,
  safeHref,
  scopeLabel,
  textValue,
  time,
  words,
} from "./format";
import type { Action, Folio, RichValue } from "./types";

export function Mark({ small = false }: { small?: boolean }) {
  return (
    <svg
      className={small ? "brand-mark small" : "brand-mark"}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M29 5H11L4 20l7 15h18l7-15L29 5Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="M25 12H15l-4 8 4 8h10" stroke="currentColor" strokeWidth="2.5" />
      <path
        d="M22 20h15M20 2v6M20 32v6"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="20" cy="20" r="2" fill="currentColor" />
    </svg>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: "primary" | "secondary" | "quiet" | "danger";
  busy?: boolean;
  icon?: ReactNode;
  arrow?: boolean;
};
export function Button({
  tone = "secondary",
  busy,
  icon,
  arrow,
  children,
  className = "",
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button-${tone} ${className}`}
      disabled={disabled || busy}
      {...props}
    >
      {busy ? (
        <LoaderCircle size={16} className="spin" aria-hidden="true" />
      ) : (
        icon
      )}
      {children}
      {arrow ? <ArrowRight size={17} aria-hidden="true" /> : null}
    </button>
  );
}

export function IconButton({
  label,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
}) {
  return (
    <button
      className={`icon-button ${className}`}
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "teal" | "blue" | "purple" | "rust" | "ochre" | "error";
}) {
  return (
    <span className={`pill pill-${tone}`}>
      <span className="pill-dot" aria-hidden="true" />
      {children}
    </span>
  );
}

export function ScopePill({ scope }: { scope?: string }) {
  return (
    <Pill
      tone={
        scope === "in_scope"
          ? "teal"
          : scope === "applicability"
            ? "rust"
            : "neutral"
      }
    >
      {scopeLabel(scope)}
    </Pill>
  );
}

export function SectionHeading({
  number,
  title,
  children,
}: {
  number?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <h2>
        {number ? <span className="section-number">{number}</span> : null}
        {title}
      </h2>
      {children ? (
        <div className="section-heading-aside">{children}</div>
      ) : null}
    </div>
  );
}

export function Notice({
  title,
  children,
  tone = "neutral",
}: {
  title?: string;
  children: ReactNode;
  tone?: "neutral" | "blue" | "teal" | "ochre" | "error" | "rust";
}) {
  const Icon =
    tone === "error" ? CircleAlert : tone === "teal" ? ShieldCheck : Info;
  return (
    <div className={`notice notice-${tone}`}>
      <Icon size={18} aria-hidden="true" />
      <div>
        {title ? <strong>{title}</strong> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}

export function InlineError({
  message,
  title,
}: {
  message?: string;
  title: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!message) return;
    ref.current?.focus({ preventScroll: true });
    ref.current?.scrollIntoView({ behavior: "instant", block: "center" });
  }, [message]);
  return message ? (
    <div
      className="dialog-error-summary"
      ref={ref}
      tabIndex={-1}
      role="alert"
      aria-label={title}
    >
      <Notice tone="error" title={title}>
        {message}
      </Notice>
    </div>
  ) : null;
}

export function ExternalSource({
  url,
  children,
  className = "",
}: {
  url?: string;
  children: ReactNode;
  className?: string;
}) {
  const href = safeHref(url);
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`external-source ${className}`}
    >
      {children}
      <ExternalLink size={13} aria-hidden="true" />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ) : (
    <span className={className}>{children}</span>
  );
}

export function Hash({
  value,
  label = "SHA-256",
}: {
  value?: string;
  label?: string;
}) {
  return (
    <div className="hash-line">
      <span>{label}</span>
      <code title={value}>{hashShort(value)}</code>
      {value ? <CopyHash value={value} /> : null}
    </div>
  );
}

function CopyHash({ value }: { value: string }) {
  const [labelId] = [useId()];
  const status = useRef<HTMLSpanElement>(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      if (status.current) status.current.textContent = "Copied";
    } catch {
      if (status.current) status.current.textContent = "Copy unavailable";
    }
  }
  return (
    <>
      <button
        className="text-button hash-copy"
        type="button"
        onClick={() => void copy()}
        aria-describedby={labelId}
      >
        Copy
      </button>
      <span className="sr-only" id={labelId} ref={status} role="status" />
    </>
  );
}

export function RichText({
  value,
  fallback = "Not specified",
  className = "",
}: {
  value?: RichValue | unknown;
  fallback?: string;
  className?: string;
}) {
  return (
    <p className={`rich-text ${className}`}>
      {value === null || value === undefined || value === ""
        ? fallback
        : textValue(value)}
    </p>
  );
}

export function ArtifactLink({
  sha,
  children = "Inspect artifact",
}: {
  sha?: string;
  children?: ReactNode;
}) {
  return sha ? (
    <a
      className="text-link artifact-link"
      href={artifactUrl(sha)}
      target="_blank"
      rel="noreferrer"
    >
      <ArrowDownToLine size={15} aria-hidden="true" />
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ) : null;
}

export function Dialog({
  open,
  onDismiss,
  title,
  eyebrow,
  children,
  className = "",
}: {
  open: boolean;
  onDismiss: () => void;
  title: string;
  eyebrow?: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const dismissRef = useRef(onDismiss);
  useEffect(() => {
    dismissRef.current = onDismiss;
  }, [onDismiss]);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={`dialog ${className}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        dismissRef.current();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) dismissRef.current();
      }}
    >
      <div className="dialog-inner">
        <header className="dialog-header">
          <div>
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            <h2 id={titleId}>{title}</h2>
          </div>
          <IconButton label="Close dialog" onClick={onDismiss}>
            <X size={20} />
          </IconButton>
        </header>
        {children}
      </div>
    </dialog>
  );
}

const actionLabels: Partial<Record<Action | "prepare", string>> = {
  prepare: "Preparing source and sealed plan",
  propose_contract: "Drafting the research contract",
  reproduce: "Running the original comparison",
  retrieve: "Retrieving primary-source evidence",
  explore: "Testing the finite condition lattice",
  confirm: "Computing registered predictions",
  verify: "Verifying the sealed evidence",
};

export function RunBanner({
  folio,
  pending,
  onAction,
  onInspect,
}: {
  folio: Folio;
  pending: string | null;
  onAction: (action: Action) => void;
  onInspect: () => void;
}) {
  const run = folio.run;
  if (!run) return null;
  const active = isActive(folio);
  const failed =
    ["failed", "interrupted", "cancelled"].includes(folio.status) ||
    ["failed", "interrupted", "cancelled"].includes(run.status);
  if (!active && !failed) return null;
  const cancelled =
    folio.status === "cancel_requested" || run.status === "cancel_requested";
  const completed = run.completed_units;
  const total = run.total_units;
  const hasUnits = finite(completed) && finite(total) && total > 0;
  return (
    <section
      className={`run-banner ${failed ? "run-banner-failed" : ""}`}
      aria-label="Current operation"
    >
      <div className="run-banner-main">
        <span
          className={`run-symbol ${active && !cancelled ? "is-running" : ""}`}
        >
          {failed ? (
            <CircleAlert size={19} />
          ) : cancelled ? (
            <Pause size={19} />
          ) : (
            <LoaderCircle size={19} />
          )}
        </span>
        <div className="run-banner-copy">
          <div className="run-banner-title">
            <strong>
              {failed
                ? `${words(run.status)} operation`
                : cancelled
                  ? "Cancellation requested"
                  : (actionLabels[run.action as Action] ?? words(run.action))}
            </strong>
            <span className="mono">Attempt {run.attempt ?? 1}</span>
          </div>
          <p>
            {failed
              ? textValue(
                  run.error ??
                    "The operation stopped before committing a complete result. Saved checkpoints remain available.",
                )
              : textValue(
                  run.checkpoint ?? "Waiting for the first durable checkpoint.",
                )}
          </p>
          {hasUnits ? (
            <div className="verified-progress">
              <progress max={total} value={completed} />
              <span className="mono">
                {completed} / {total} {run.unit_label ?? "verified units"}
              </span>
            </div>
          ) : null}
          <div className="run-banner-meta">
            <span>
              Heartbeat{" "}
              <time dateTime={run.heartbeat_at}>{time(run.heartbeat_at)}</time>
            </span>
            <button className="text-button" onClick={onInspect}>
              Activity & receipts <ArrowRight size={13} />
            </button>
          </div>
          {failed ? (
            <p className="run-integrity-note">
              An operational stop does not decide the scientific claim.
            </p>
          ) : null}
        </div>
      </div>
      <div className="run-banner-actions">
        {active ? (
          <Button
            tone="quiet"
            icon={<Pause size={15} />}
            busy={pending === "cancel"}
            disabled={cancelled}
            onClick={() => onAction("cancel")}
          >
            {cancelled ? "Stopping safely…" : "Cancel operation"}
          </Button>
        ) : run.can_resume ? (
          <Button
            icon={<Play size={15} />}
            busy={pending === "resume"}
            onClick={() => onAction("resume")}
          >
            Resume saved attempt
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export function ReviewStamp({
  name,
  timestamp,
  note,
  label = "Local operator review",
}: {
  name: string;
  timestamp?: string;
  note?: string;
  label?: string;
}) {
  const automated = /automated|\(agent\)|scripted local/i.test(
    `${name} ${note ?? ""}`,
  );
  return (
    <div className="review-stamp">
      <span className="review-seal">
        <Check size={17} aria-hidden="true" />
      </span>
      <div>
        <span className="eyebrow">
          {automated ? "AUTOMATED OPERATOR RECORD · AGENT QA" : label}
        </span>
        <p>
          <strong>{name}</strong>
          {timestamp ? <span> · {dateTime(timestamp)}</span> : null}
        </p>
        {note ? <p className="review-note">{note}</p> : null}
        {automated ? (
          <p className="automated-review-note">
            Recorded during an agent-run workflow check. Human scientific
            approval remains pending.
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function BusyPage({
  label = "Opening the evidence folio",
}: {
  label?: string;
}) {
  return (
    <div className="busy-page" role="status">
      <Mark />
      <p>{label}</p>
      <span>Reading the saved record.</span>
    </div>
  );
}
