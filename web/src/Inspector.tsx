import { useRef, useState } from "react";
import { useProviderStatus } from "./provider";
import {
  ArrowUpRight,
  Check,
  CheckCheck,
  Clock3,
  Database,
  FileSearch,
  Fingerprint,
  LockKeyhole,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  conditionLabel,
  dateTime,
  effect,
  finite,
  integer,
  percent,
  reviewDate,
  reviewName,
  reviewNote,
  scopeLabel,
  words,
} from "./format";
import type {
  Folio,
  InspectorTab,
  Observation,
  Receipt,
  ReviewRecord,
} from "./types";
import {
  ArtifactLink,
  ExternalSource,
  Hash,
  IconButton,
  Notice,
  Pill,
  ReviewStamp,
  RichText,
} from "./ui";
import { SeedSpread } from "./figures";

const tabs: { id: InspectorTab; label: string }[] = [
  { id: "source", label: "Source" },
  { id: "data", label: "Data" },
  { id: "computation", label: "Compute" },
  { id: "review", label: "Review" },
  { id: "activity", label: "Log" },
];

export function Inspector({
  folio,
  tab,
  onTab,
  selectedCondition,
  onClose,
  embedded = false,
}: {
  folio: Folio;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  selectedCondition: string | null;
  onClose?: () => void;
  embedded?: boolean;
}) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const observations = folio.observations ?? [];
  const matching = observations.filter(
    (observation) => observation.condition_id === selectedCondition,
  );
  const observation =
    matching.find((observation) => observation.phase === "confirmation") ??
    matching.find((observation) => observation.phase === "discovery") ??
    matching[0] ??
    observations.find((observation) => observation.phase === "confirmation") ??
    observations[0];
  return (
    <aside
      className={`inspector ${embedded ? "inspector-embedded" : ""}`}
      aria-label="Evidence trail"
    >
      {!embedded ? (
        <header className="inspector-header">
          <div>
            <span className="eyebrow">SOURCE → COMPUTATION</span>
            <h2>Evidence trail</h2>
          </div>
          {onClose ? (
            <IconButton label="Close evidence trail" onClick={onClose}>
              <X size={18} />
            </IconButton>
          ) : (
            <Fingerprint size={22} strokeWidth={1.2} aria-hidden="true" />
          )}
        </header>
      ) : null}
      <div
        className="inspector-tabs"
        role="tablist"
        aria-label="Evidence inspection"
      >
        {tabs.map((item, index) => (
          <button
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            key={item.id}
            role="tab"
            id={`inspect-tab-${item.id}`}
            aria-controls={`inspect-panel-${item.id}`}
            aria-selected={tab === item.id}
            tabIndex={tab === item.id ? 0 : -1}
            onClick={() => onTab(item.id)}
            onKeyDown={(event) => {
              let next = index;
              if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
              else if (event.key === "ArrowLeft")
                next = (index + tabs.length - 1) % tabs.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = tabs.length - 1;
              else return;
              event.preventDefault();
              onTab(tabs[next].id);
              tabRefs.current[next]?.focus();
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        className="inspector-content"
        role="tabpanel"
        id={`inspect-panel-${tab}`}
        aria-labelledby={`inspect-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "source" ? (
          <SourcePanel folio={folio} />
        ) : tab === "data" ? (
          <DataPanel folio={folio} />
        ) : tab === "computation" ? (
          <ComputationPanel folio={folio} observation={observation} />
        ) : tab === "review" ? (
          <ReviewPanel folio={folio} />
        ) : (
          <ActivityPanel folio={folio} />
        )}
      </div>
      <footer className="inspector-footer">
        <LockKeyhole size={13} />
        <span>Private local workbench · revision {folio.revision}</span>
      </footer>
    </aside>
  );
}

function PanelHeading({
  marker,
  title,
  children,
}: {
  marker: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="inspector-section-heading">
      <span className="inspector-marker">{marker}</span>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function SourcePanel({ folio }: { folio: Folio }) {
  const source = folio.source;
  return (
    <>
      <PanelHeading marker="S1" title="The source record" />
      {!source ? (
        <Notice title="Source not yet available">
          Source preparation has not committed a source manifest. Follow the
          operation log for the actual status.
        </Notice>
      ) : (
        <>
          <span className="inspector-eyebrow">
            {folio.adapter_id === "synthetic"
              ? "CONTROLLED SYNTHETIC CASE"
              : "PUBLIC DATA · AUTHORED COMPARISON"}
          </span>
          <h4 className="inspector-source-title">
            <ExternalSource url={source.url}>{source.title}</ExternalSource>
          </h4>
          <RichText value={source.description} />
          {source.source_span ? (
            <div className="source-span">
              <span className="eyebrow">EXACT SOURCE / AUTHORED SPAN</span>
              <RichText value={source.source_span} />
            </div>
          ) : (
            <p className="inspector-note">
              No paper source span is supplied for this authored comparison.
            </p>
          )}
          <dl className="inspector-definitions">
            <div>
              <dt>Data license</dt>
              <dd>{source.license ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Attribution</dt>
              <dd>{source.attribution ?? "Not recorded"}</dd>
            </div>
            <div>
              <dt>Case type</dt>
              <dd>
                {folio.adapter_id === "synthetic"
                  ? "Controlled synthetic experiment"
                  : "Authored comparison on UCI public data"}
              </dd>
            </div>
          </dl>
          <Hash
            value={source.sha256}
            label={
              folio.adapter_id === "occupancy"
                ? "Source archive SHA-256"
                : "Generator/source SHA-256"
            }
          />
          <Notice tone="ochre" title="Qualification remains open">
            This case does not assert a reproduction of the linked paper’s
            protocol. The data license does not establish redistribution rights
            for that paper or its code.
          </Notice>
        </>
      )}
      <PanelHeading marker="C1" title="The claim being tested" />
      <blockquote className="inspector-claim">
        {folio.contract?.claim ?? folio.claim}
      </blockquote>
      <p className="inspector-note">
        Authored locally. A model proposal may suggest wording; a local operator
        must review the locked contract.
      </p>
    </>
  );
}

function DataPanel({ folio }: { folio: Folio }) {
  return (
    <>
      <PanelHeading marker="D1" title="Frozen before fitting" />
      <RichText
        value={folio.contract?.split}
        fallback="The split plan has not yet been prepared."
      />
      <div className="inspector-rule-note">
        <Database size={17} />
        <p>
          Training, discovery, and confirmation have different roles. Discovery
          informs the question; a registered confirmation uses the reserved
          partition.
        </p>
      </div>
      <PanelHeading marker="D2" title="The pinned files" />
      {folio.source?.files?.length ? (
        <div className="source-file-list">
          {folio.source.files.map((file) => (
            <article key={file.name}>
              <div className="source-file-heading">
                <FileSearch size={15} />
                <strong>{file.name}</strong>
              </div>
              <div className="file-metadata">
                <span>
                  {file.split ? words(file.split) : "Split not recorded"}
                </span>
                <span>{integer(file.rows)} rows</span>
              </div>
              <Hash value={file.sha256} />
            </article>
          ))}
        </div>
      ) : (
        <p className="inspector-note">No file manifest is available yet.</p>
      )}
      <PanelHeading marker="D3" title="Preprocessing permissions" />
      <RichText value={folio.contract?.preprocessing} />
      <PanelHeading marker="D4" title="The data audit" />
      <RichText
        value={folio.source?.audit}
        fallback="Audit output is not yet available. No audit pass is assumed."
      />
      {folio.registration ? (
        <div className="sealed-note">
          <LockKeyhole size={17} />
          <div>
            <strong>Confirmation is registered</strong>
            <p>
              {folio.registration.holdout_status
                ? `Recorded holdout state: ${words(folio.registration.holdout_status)}.`
                : "Inspect the registration and verifier record for holdout use."}
            </p>
          </div>
        </div>
      ) : null}
    </>
  );
}

function Measurement({
  folio,
  observation,
}: {
  folio: Folio;
  observation: Observation;
}) {
  return (
    <>
      <PanelHeading marker="M1" title="Pinned measurement" />
      <div className="measurement-id">
        <span className="inspector-eyebrow">{words(observation.phase)}</span>
        <h4>
          {observation.condition_label ??
            conditionLabel(folio, observation.condition_id)}
        </h4>
        <Pill tone={observation.scope === "applicability" ? "rust" : "teal"}>
          {scopeLabel(observation.scope)}
        </Pill>
      </div>
      <div className="inspector-measurement">
        <strong>
          {effect(observation.effect)}
          <small> pp</small>
        </strong>
        <span>candidate − baseline</span>
      </div>
      <dl className="inspector-definitions">
        <div>
          <dt>Candidate</dt>
          <dd className="mono">{percent(observation.candidate)}</dd>
        </div>
        <div>
          <dt>Baseline</dt>
          <dd className="mono">{percent(observation.baseline)}</dd>
        </div>
        <div>
          <dt>Descriptive interval</dt>
          <dd className="mono">
            {finite(observation.ci_low) && finite(observation.ci_high)
              ? `${effect(observation.ci_low)} to ${effect(observation.ci_high)} pp`
              : "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Analysis unit</dt>
          <dd>{observation.unit ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Usable blocks</dt>
          <dd className="mono">{integer(observation.blocks)}</dd>
        </div>
        <div>
          <dt>Analyzed / predicted rows</dt>
          <dd className="mono">
            {integer(observation.analyzed_rows)} / {integer(observation.rows)}
          </dd>
        </div>
        <div>
          <dt>Interval method</dt>
          <dd>{observation.interval_method ?? "Not recorded"}</dd>
        </div>
      </dl>
      {observation.warning ? (
        <Notice tone="ochre">
          <RichText value={observation.warning} />
        </Notice>
      ) : null}
      <SeedSpread observation={observation} />
      <ArtifactLink sha={observation.artifact_sha256}>
        Open measurement artifact
      </ArtifactLink>
    </>
  );
}

function ReceiptView({ receipt }: { receipt: Receipt }) {
  return (
    <article className="receipt">
      <div className="receipt-topline">
        <strong>{receipt.provider ?? words(receipt.kind)}</strong>
        <Pill
          tone={
            ["failed", "rejected", "error"].includes(receipt.status)
              ? "error"
              : ["complete", "completed", "succeeded", "success"].includes(
                    receipt.status,
                  )
                ? "teal"
                : "neutral"
          }
        >
          {words(receipt.status)}
        </Pill>
      </div>
      {receipt.model ? (
        <p className="receipt-model mono">{receipt.model}</p>
      ) : null}
      {receipt.purpose ? <p>{receipt.purpose}</p> : null}
      <dl>
        <div>
          <dt>Started</dt>
          <dd>{dateTime(receipt.started_at)}</dd>
        </div>
        <div>
          <dt>Actual duration</dt>
          <dd>
            {finite(receipt.elapsed_ms)
              ? `${(receipt.elapsed_ms / 1000).toFixed(1)} s`
              : "Not returned"}
          </dd>
        </div>
        {finite(receipt.input_tokens) || finite(receipt.output_tokens) ? (
          <div>
            <dt>Input / output tokens</dt>
            <dd>
              {finite(receipt.input_tokens)
                ? integer(receipt.input_tokens)
                : "—"}{" "}
              /{" "}
              {finite(receipt.output_tokens)
                ? integer(receipt.output_tokens)
                : "—"}
            </dd>
          </div>
        ) : null}
        {finite(receipt.estimated_cost_usd) ? (
          <div>
            <dt>Estimated cost</dt>
            <dd>${receipt.estimated_cost_usd.toFixed(4)}</dd>
          </div>
        ) : null}
      </dl>
      {receipt.request_id ? (
        <p className="receipt-request">
          Request <code>{receipt.request_id}</code>
        </p>
      ) : null}
      {receipt.error ? <p className="receipt-error">{receipt.error}</p> : null}
      <span className="receipt-id mono">{receipt.id}</span>
    </article>
  );
}

function ComputationPanel({
  folio,
  observation,
}: {
  folio: Folio;
  observation?: Observation;
}) {
  const { label, nebiusQualification } = useProviderStatus();
  return (
    <>
      {observation ? (
        <Measurement folio={folio} observation={observation} />
      ) : (
        <>
          <PanelHeading marker="M1" title="No measurement yet" />
          <p className="inspector-note">
            A proposed effect is not an observed result. Computed measurements
            will appear here after a complete operation.
          </p>
        </>
      )}
      <PanelHeading marker="V1" title="The verifier" />
      {folio.verification ? (
        <>
          <Pill
            tone={folio.verification.status === "verified" ? "teal" : "error"}
          >
            {words(folio.verification.status)}
          </Pill>
          <RichText value={folio.verification.method} />
          <RichText value={folio.verification.independence} />
          <ArtifactLink sha={folio.verification.artifact_sha256}>
            Verifier artifact
          </ArtifactLink>
          <Hash value={folio.verification.sha256} label="Verifier SHA-256" />
        </>
      ) : (
        <p className="inspector-note">
          No independent verifier result is recorded. Model reasoning cannot
          replace this computation.
        </p>
      )}
      <PanelHeading marker="R1" title="Provider & execution receipts" />
      {folio.receipts?.length ? (
        <div className="receipt-list">
          {[...folio.receipts].reverse().map((receipt) => (
            <ReceiptView key={receipt.id} receipt={receipt} />
          ))}
        </div>
      ) : (
        <p className="inspector-note">
          No completed or failed provider receipt is recorded yet.
        </p>
      )}
      <details className="raw-spec">
        <summary>Inspect the locked configuration</summary>
        <pre>
          {JSON.stringify(
            {
              schema_version: folio.contract?.schema_version,
              contract_revision: folio.contract?.revision,
              candidate: folio.contract?.candidate,
              baseline: folio.contract?.baseline,
              metric: folio.contract?.metric,
              practical_delta: folio.contract?.practical_delta,
              alpha: folio.contract?.alpha,
              seeds: folio.contract?.seeds,
              analysis: folio.contract?.analysis,
            },
            null,
            2,
          )}
        </pre>
      </details>
      <p className="qualification-note">
        Configured inference route: {label}. Nebius qualification:
        {nebiusQualification}. Receipts identify the provider actually used for
        each recorded request.
      </p>
    </>
  );
}

function ReviewBlock({
  title,
  review,
}: {
  title: string;
  review?: ReviewRecord | null;
}) {
  return (
    <div className="inspector-review-block">
      <h4>{title}</h4>
      {review ? (
        <ReviewStamp
          name={reviewName(review)}
          timestamp={reviewDate(review)}
          note={reviewNote(review)}
        />
      ) : (
        <p className="inspector-note">No local review is recorded.</p>
      )}
    </div>
  );
}

function ReviewPanel({ folio }: { folio: Folio }) {
  const evidence = folio.evidence_change;
  return (
    <>
      <PanelHeading marker="H1" title="Local operator decisions" />
      <Notice title="A precise reviewer role">
        These records identify the local user’s review. External methodologist
        approval and paper-protocol qualification are pending.
      </Notice>
      <ReviewBlock title="Contract review" review={folio.contract?.approval} />
      <Hash value={folio.contract?.sha256} label="Reviewed contract SHA-256" />
      <div className="inspector-review-block">
        <h4>Reproduction review</h4>
        {folio.reproduction_review ? (
          <ReviewStamp
            name={reviewName(folio.reproduction_review)}
            timestamp={reviewDate(folio.reproduction_review)}
            note={reviewNote(folio.reproduction_review)}
          />
        ) : folio.events?.filter((event) =>
            /accept.*reproduction|reproduction.*accept|baseline.*review/i.test(
              `${event.type} ${event.message}`,
            ),
          ).length ? (
          folio.events
            .filter((event) =>
              /accept.*reproduction|reproduction.*accept|baseline.*review/i.test(
                `${event.type} ${event.message}`,
              ),
            )
            .map((event) => (
              <div className="review-event" key={event.seq}>
                <CheckCheck size={15} />
                <div>
                  <p>{event.message}</p>
                  <time dateTime={event.created_at}>
                    {dateTime(event.created_at)}
                  </time>
                </div>
              </div>
            ))
        ) : (
          <p className="inspector-note">
            Inspect the activity ledger for the reproduction review event.
          </p>
        )}
      </div>
      <div className="inspector-review-block">
        <h4>Evidence change</h4>
        {evidence ? (
          <>
            <Pill
              tone={
                evidence.status === "accepted"
                  ? "teal"
                  : evidence.status === "proposed"
                    ? "ochre"
                    : "neutral"
              }
            >
              {words(evidence.status)}
            </Pill>
            <RichText value={evidence.assumption} />
            <RichText
              value={evidence.decision}
              fallback="No decision recorded."
            />
            {evidence.source ? (
              <ExternalSource url={evidence.source.url}>
                {evidence.source.title}
              </ExternalSource>
            ) : null}
          </>
        ) : (
          <p className="inspector-note">No evidence proposal is recorded.</p>
        )}
      </div>
      {folio.registration ? (
        <div className="inspector-review-block">
          <h4>
            <LockKeyhole size={15} />
            Confirmation registration
          </h4>
          <p>{conditionLabel(folio, folio.registration.condition_id)}</p>
          <p className="inspector-note">
            {folio.registration.reviewer_name ?? "Local operator"} ·{" "}
            {dateTime(folio.registration.registered_at)}
          </p>
          <Hash value={folio.registration.sha256} />
        </div>
      ) : null}
      <ReviewBlock
        title="Bounded conclusion review"
        review={folio.conclusion?.review}
      />
      {folio.conclusion ? (
        <div className="inspector-rule-note">
          <ShieldCheck size={17} />
          <p>{folio.conclusion.statement}</p>
        </div>
      ) : null}
    </>
  );
}

function ActivityPanel({ folio }: { folio: Folio }) {
  const [limit, setLimit] = useState(12);
  const events = [...(folio.events ?? [])].sort((a, b) => b.seq - a.seq);
  return (
    <>
      <PanelHeading marker="L1" title="The durable activity ledger">
        <Clock3 size={15} />
      </PanelHeading>
      <p className="inspector-note">
        Events come from the API’s persisted record. Failed attempts and
        cancellations remain part of the folio.
      </p>
      <ol className="event-list">
        {events.slice(0, limit).map((event) => (
          <li key={event.seq}>
            <span className="event-seq mono">
              {String(event.seq).padStart(2, "0")}
            </span>
            <div>
              <span className="event-type">{words(event.type)}</span>
              <p>{event.message}</p>
              <time dateTime={event.created_at}>
                {dateTime(event.created_at)}
              </time>
              {event.run_id ? (
                <code className="event-run">{event.run_id}</code>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      {!events.length ? (
        <p className="inspector-note">No events are available yet.</p>
      ) : null}
      {events.length > limit ? (
        <button
          className="button button-secondary"
          onClick={() => setLimit((current) => current + 20)}
        >
          Show earlier events <ArrowUpRight size={14} />
        </button>
      ) : null}
      <div className="log-end">
        <Check size={14} />
        <span>
          {events.length} persisted {events.length === 1 ? "event" : "events"}{" "}
          in this response
        </span>
      </div>
    </>
  );
}
