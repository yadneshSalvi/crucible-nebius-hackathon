import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Check,
  CheckCheck,
  ClipboardCheck,
  FileArchive,
  FileText,
  FlaskConical,
  LockKeyhole,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { exportUrl } from "./api";
import { useProviderStatus } from "./provider";
import {
  activeConditionIds,
  bytes,
  conditionLabel,
  dateTime,
  effect,
  finite,
  hashShort,
  isActive,
  outcomeLabel,
  reproductionAccepted,
  reviewDate,
  reviewName,
  reviewNote,
  textValue,
  words,
} from "./format";
import {
  ConditionAtlas,
  EffectPlot,
  ResultStats,
  SeedSpread,
  SelectedCondition,
} from "./figures";
import type { Action, Folio, InspectorTab, Stage } from "./types";
import {
  ArtifactLink,
  Button,
  ExternalSource,
  Hash,
  Notice,
  Pill,
  ReviewStamp,
  RichText,
  ScopePill,
  SectionHeading,
} from "./ui";

export type ReviewAction =
  | "lock_contract"
  | "accept_reproduction"
  | "accept_evidence"
  | "reject_evidence"
  | "register_confirmation"
  | "review_conclusion";
export interface StageProps {
  folio: Folio;
  pending: string | null;
  selectedCondition: string | null;
  onSelectCondition: (condition: string) => void;
  onAction: (
    action: Action,
    body?: Record<string, unknown>,
    nextStage?: Stage,
  ) => Promise<boolean>;
  onReview: (action: ReviewAction, condition?: string) => void;
  onInspect: (tab: InspectorTab) => void;
  onNavigate: (stage: Stage) => void;
}

export function StageTitle({
  number,
  eyebrow,
  title,
  description,
  children,
}: {
  number: string;
  eyebrow: string;
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="stage-title">
      <div className="stage-kicker">
        <span className="eyebrow">{eyebrow}</span>
        <span className="folio-page">
          {number}
          <span>/05</span>
        </span>
      </div>
      <h1>{title}</h1>
      {description ? <p className="stage-description">{description}</p> : null}
      {children}
    </header>
  );
}

function SourceFootnote({
  folio,
  onInspect,
}: {
  folio: Folio;
  onInspect: () => void;
}) {
  return (
    <div className="source-footnote">
      <span className="source-marker">S1</span>
      <div>
        <strong>
          {folio.case_kind === "controlled_synthetic" ||
          folio.adapter_id === "synthetic"
            ? "Controlled synthetic case"
            : "Authored comparison on public data"}
        </strong>
        <p>
          {folio.source?.title ?? "Source preparation is pending."}
          {folio.adapter_id === "occupancy"
            ? " · This does not reproduce the linked paper’s original protocol."
            : ""}
        </p>
      </div>
      <button className="text-button" onClick={onInspect}>
        Source <ArrowUpRight size={14} />
      </button>
    </div>
  );
}

function MethodPair({ folio }: { folio: Folio }) {
  return (
    <div className="method-pair">
      <div>
        <span className="eyebrow">
          <span className="method-dot candidate-dot" />
          CANDIDATE
        </span>
        <h3>{folio.contract?.candidate?.name ?? "Not specified"}</h3>
        <RichText
          value={folio.contract?.candidate?.parameters}
          fallback="Parameters are pending preparation."
        />
      </div>
      <div>
        <span className="eyebrow">
          <span className="method-dot baseline-dot" />
          BASELINE
        </span>
        <h3>{folio.contract?.baseline?.name ?? "Not specified"}</h3>
        <RichText
          value={folio.contract?.baseline?.parameters}
          fallback="Parameters are pending preparation."
        />
      </div>
    </div>
  );
}

function NextStep({
  eyebrow = "NEXT IN THE ARGUMENT",
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="next-step">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h3>{title}</h3>
      </div>
      {children}
    </div>
  );
}

export function ContractStage(props: StageProps) {
  const { label: providerLabel } = useProviderStatus();
  const { folio, pending, onAction, onReview, onInspect, onNavigate } = props;
  const contract = folio.contract;
  const [title, setTitle] = useState(folio.title);
  const [claim, setClaim] = useState(contract?.claim ?? folio.claim);
  const [delta, setDelta] = useState(
    String((contract?.practical_delta ?? 0) * 100),
  );
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (!dirty) {
      setTitle(folio.title);
      setClaim(contract?.claim ?? folio.claim);
      setDelta(String((contract?.practical_delta ?? 0) * 100));
    }
  }, [
    folio.id,
    folio.title,
    folio.claim,
    contract?.claim,
    contract?.practical_delta,
    contract?.revision,
    dirty,
  ]);
  const busy = isActive(folio) || Boolean(pending);
  const locked = Boolean(contract?.locked);
  const margin = Number(delta);
  const validDraft =
    title.trim().length >= 3 &&
    title.trim().length <= 120 &&
    claim.trim().length >= 20 &&
    claim.trim().length <= 800 &&
    delta !== "" &&
    finite(margin) &&
    margin >= 0 &&
    margin <= 10;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (
      validDraft &&
      (await onAction("update_contract", {
        title: title.trim(),
        claim: claim.trim(),
        practical_delta: margin / 100,
      }))
    )
      setDirty(false);
  }
  const fields: {
    label: string;
    value: unknown;
    tab: InspectorTab;
    caption?: string;
  }[] = [
    { label: "Population", value: contract?.population, tab: "data" },
    { label: "Evaluation split", value: contract?.split, tab: "data" },
    {
      label: "Preprocessing",
      value: contract?.preprocessing,
      tab: "computation",
    },
    {
      label: "Analysis & uncertainty",
      value: contract?.analysis,
      tab: "computation",
    },
    { label: "Registered scope", value: contract?.scope, tab: "review" },
  ];
  return (
    <>
      <StageTitle
        number="01"
        eyebrow="THE RESEARCH CONTRACT"
        title="Make the comparison precise."
        description="A testable claim starts with declared methods, a meaningful difference, and a clear limit on what the evidence can say."
      />
      <SourceFootnote folio={folio} onInspect={() => onInspect("source")} />
      {!contract ? (
        <Notice title="Preparing the trusted adapter" tone="blue">
          The source manifest and sealed split plan must be prepared before you
          can review this contract. Progress appears above as the API commits
          checkpoints.
        </Notice>
      ) : (
        <>
          {locked ? (
            <div className="locked-contract">
              <LockKeyhole size={18} aria-hidden="true" />
              <div>
                <strong>Contract revision {contract.revision} is locked</strong>
                <p>Results remain attached to this reviewed specification.</p>
              </div>
              <button
                className="text-button"
                onClick={() => onInspect("review")}
              >
                Review record <ArrowUpRight size={14} />
              </button>
            </div>
          ) : null}
          <section className="claim-section">
            <SectionHeading number="01" title="The claim">
              {locked ? (
                <Pill tone="teal">Reviewed contract</Pill>
              ) : (
                <Pill tone="ochre">Draft · review required</Pill>
              )}
            </SectionHeading>
            <form
              onSubmit={(event) => void save(event)}
              className="contract-form"
            >
              <label className="field-label" htmlFor="folio-title">
                Folio title
              </label>
              <input
                id="folio-title"
                className="title-input"
                value={title}
                maxLength={120}
                onChange={(event) => {
                  setTitle(event.target.value);
                  setDirty(true);
                }}
                disabled={locked || busy}
                required
              />
              <label className="field-label" htmlFor="claim">
                Authored claim to test
              </label>
              <textarea
                id="claim"
                className="claim-editor"
                value={claim}
                onChange={(event) => {
                  setClaim(event.target.value);
                  setDirty(true);
                }}
                disabled={locked || busy}
                required
                maxLength={800}
                rows={4}
              />
              <div className="margin-setting">
                <div>
                  <label htmlFor="practical-margin">
                    Minimum practical difference
                  </label>
                  <p>
                    Candidate − baseline in balanced accuracy. Declared before
                    viewing results.
                  </p>
                </div>
                <div className="margin-input-wrap">
                  <input
                    id="practical-margin"
                    type="number"
                    min="0"
                    max="10"
                    step="0.1"
                    value={delta}
                    onChange={(event) => {
                      setDelta(event.target.value);
                      setDirty(true);
                    }}
                    disabled={locked || busy}
                    required
                    aria-describedby="margin-unit"
                  />
                  <span id="margin-unit">pp</span>
                </div>
              </div>
              {!locked ? (
                <div className="contract-form-actions">
                  <span className={dirty ? "unsaved-label" : "saved-label"}>
                    {dirty
                      ? "Local edits · save a revision to keep them"
                      : `Saved revision ${contract.revision}`}
                  </span>
                  <Button
                    type="submit"
                    disabled={!dirty || !validDraft || busy}
                    busy={pending === "update_contract"}
                    icon={<Check size={16} />}
                  >
                    Save revision
                  </Button>
                </div>
              ) : null}
            </form>
          </section>
          <section>
            <SectionHeading number="02" title="The comparison" />
            <MethodPair folio={folio} />
            <div className="metric-rule">
              <span className="eyebrow">PRIMARY METRIC</span>
              <strong>{words(contract.metric ?? "balanced_accuracy")}</strong>
              <span className="mono">Higher is better · paired difference</span>
            </div>
          </section>
          <section>
            <SectionHeading number="03" title="What stays fixed">
              <button
                className="text-button"
                onClick={() => onInspect("computation")}
              >
                Inspect specification <ArrowUpRight size={14} />
              </button>
            </SectionHeading>
            <dl className="contract-definitions">
              {fields.map((field) => (
                <div key={field.label}>
                  <dt>{field.label}</dt>
                  <dd>
                    <button onClick={() => onInspect(field.tab)}>
                      <span>{textValue(field.value)}</span>
                      <ArrowUpRight size={15} aria-hidden="true" />
                    </button>
                  </dd>
                </div>
              ))}
              <div>
                <dt>Training seeds</dt>
                <dd>
                  <span className="mono">
                    {contract.seeds?.length
                      ? contract.seeds.join(" · ")
                      : "Not recorded"}
                  </span>
                  <small>Repeated fits, not independent datasets.</small>
                </dd>
              </div>
              <div>
                <dt>Type I error rate</dt>
                <dd>
                  {finite(contract.alpha) ? (
                    <span className="mono">α = {contract.alpha}</span>
                  ) : (
                    "Not recorded"
                  )}
                  <small>
                    The locked analysis defines the confirmatory comparison
                    family.
                  </small>
                </dd>
              </div>
            </dl>
          </section>
          <section>
            <SectionHeading number="04" title="The permitted challenge space">
              <span className="mono">
                {contract.allowed_conditions?.length ?? 0} declared conditions
              </span>
            </SectionHeading>
            <p className="section-intro">
              Only these conditions may be explored. A scope change is an
              applicability question; it cannot silently rewrite the registered
              claim.
            </p>
            <div className="lattice-list">
              {(contract.allowed_conditions ?? []).map((condition) => (
                <div key={condition.id} className="lattice-row">
                  <div>
                    <strong>{condition.label}</strong>
                    <p>
                      {condition.description ?? textValue(condition.feature)}
                    </p>
                  </div>
                  <ScopePill scope={condition.scope} />
                  <span className="lattice-state">
                    {activeConditionIds(folio).includes(condition.id)
                      ? "Active schedule"
                      : "Permitted variation"}
                  </span>
                </div>
              ))}
            </div>
          </section>
          {contract.model_proposal ? (
            <section className="model-note">
              <span className="eyebrow">
                <Sparkles size={13} />
                NVIDIA CONTRACT PROPOSAL
              </span>
              <Notice tone="ochre" title="Proposed · unverified assumptions">
                Seeds describe training variability only. Inference uses
                seed-averaged block effects; seeds are not independent units for
                the t interval.
                {folio.adapter_id === "occupancy" ? (
                  <p>
                    Independence of adjacent Occupancy days is unestablished. A
                    model-supplied assumption does not establish it.
                  </p>
                ) : null}
                Review the raw proposal below against the trusted numerical
                specification.
              </Notice>
              <RichText value={contract.model_proposal} />
              <p className="fine-print">
                A model proposal is not a scientific approval. Immutable tests
                and sealed labels remain outside the proposal.
              </p>
            </section>
          ) : null}
          {!locked ? (
            <section className="contract-bottom">
              <div>
                <h2>Ready for a local review?</h2>
                <p>
                  Check the claim, scope, and practical margin. Locking
                  preserves this revision before the first fit.
                </p>
                <div className="provider-disclosure">
                  <Sparkles size={14} />
                  <span>
                    Optional drafting sends public source context and the
                    authored claim to <strong>{providerLabel}</strong>. Raw rows
                    and sealed labels are excluded.
                  </span>
                </div>
              </div>
              <div className="action-stack">
                <Button
                  icon={<Sparkles size={16} />}
                  disabled={busy || dirty || !folio.source}
                  busy={pending === "propose_contract"}
                  onClick={() => void onAction("propose_contract")}
                >
                  Ask NVIDIA to draft
                </Button>
                <Button
                  tone="primary"
                  icon={<LockKeyhole size={16} />}
                  disabled={busy || dirty || !validDraft || !folio.source}
                  onClick={() => onReview("lock_contract")}
                >
                  Review & lock contract
                </Button>
                {dirty ? (
                  <span className="fine-print">
                    Save your edits before requesting a draft or locking.
                  </span>
                ) : null}
              </div>
            </section>
          ) : (
            <>
              <ReviewStamp
                name={reviewName(contract.approval)}
                timestamp={reviewDate(contract.approval)}
                note={reviewNote(contract.approval)}
                label="CONTRACT APPROVED BY LOCAL OPERATOR"
              />
              <Hash value={contract.sha256} label="Locked contract SHA-256" />
              <NextStep title="Establish the original comparison.">
                <Button
                  tone="primary"
                  onClick={() => onNavigate("reproduction")}
                  arrow
                >
                  Go to reproduction
                </Button>
              </NextStep>
            </>
          )}
          <p className="qualification-note">
            External methodologist review and paper-protocol qualification
            remain pending. Your review records a local operator decision.
          </p>
        </>
      )}
    </>
  );
}

export function ReproductionStage(props: StageProps) {
  const { folio, pending, onAction, onReview, onInspect, onNavigate } = props;
  const observations = folio.observations.filter(
    (observation) => observation.phase === "reproduction",
  );
  const observation = observations[0];
  const busy = isActive(folio) || Boolean(pending);
  const accepted = reproductionAccepted(folio);
  return (
    <>
      <StageTitle
        number="02"
        eyebrow="THE ORIGINAL CONDITION"
        title="First, establish the comparison."
        description="Run both methods under the same locked protocol. Review this result before asking the data a different question."
      />
      <div className="claim-quotation">
        <span className="eyebrow">
          CONTRACT v{folio.contract?.revision ?? "—"}
        </span>
        <p>“{folio.contract?.claim ?? folio.claim}”</p>
        <button className="text-button" onClick={() => onInspect("source")}>
          Trace the authored claim <ArrowUpRight size={14} />
        </button>
      </div>
      {observation ? (
        <>
          <ResultStats folio={folio} observation={observation} />
          <EffectPlot
            folio={folio}
            observations={observations}
            title="The original comparison, observed."
          />
          {observation.warning ? (
            <Notice tone="ochre" title="Read the uncertainty">
              <RichText value={observation.warning} />
            </Notice>
          ) : null}
          <SeedSpread observation={observation} />
          <div className="artifact-row">
            <ArtifactLink sha={observation.artifact_sha256}>
              Original-condition measurement
            </ArtifactLink>
            <button
              className="text-button"
              onClick={() => onInspect("computation")}
            >
              Computation & receipts <ArrowUpRight size={14} />
            </button>
          </div>
        </>
      ) : (
        <section className="unrun-state">
          <div className="unrun-motif" aria-hidden="true">
            <span>C</span>
            <i />
            <span>B</span>
          </div>
          <h2>The comparison has not been measured.</h2>
          <p>
            Crucible will fit the declared candidate and baseline on training
            data, then evaluate the original condition on the predeclared
            discovery partition.
          </p>
          <MethodPair folio={folio} />
          {!folio.contract?.locked ? (
            <Button onClick={() => onNavigate("contract")} arrow>
              Review the contract first
            </Button>
          ) : (
            <Button
              tone="primary"
              icon={<FlaskConical size={16} />}
              disabled={busy || !folio.source || Boolean(folio.run?.can_resume)}
              busy={pending === "reproduce"}
              onClick={() => void onAction("reproduce")}
            >
              Run original comparison
            </Button>
          )}
          <p className="fine-print">
            The later confirmation partition remains reserved.
          </p>
        </section>
      )}
      <SourceFootnote folio={folio} onInspect={() => onInspect("source")} />
      {observation && folio.status === "baseline_review" ? (
        <section className="review-callout">
          <div className="review-callout-heading">
            <ClipboardCheck size={21} />
            <h2>Does the reproduction match the contract?</h2>
          </div>
          <p>
            Review the methods, preprocessing, split, and actual uncertainty.
            This is an authored method comparison, so acceptance does not
            certify correspondence with the original paper.
          </p>
          <Button
            tone="primary"
            icon={<CheckCheck size={16} />}
            disabled={busy}
            onClick={() => onReview("accept_reproduction")}
          >
            Review & accept reproduction
          </Button>
        </section>
      ) : accepted ? (
        <>
          <div className="accepted-line">
            <CheckCheck size={17} />
            <span>Reproduction review is recorded.</span>
            <button className="text-button" onClick={() => onInspect("review")}>
              Inspect review
            </button>
          </div>
          <NextStep title="Choose a question inside the allowed lattice.">
            <Button
              tone="primary"
              onClick={() => onNavigate("challenge")}
              arrow
            >
              Open the challenge composer
            </Button>
          </NextStep>
        </>
      ) : null}
    </>
  );
}

function EvidenceChangeView({
  folio,
  pending,
  onReview,
  onInspect,
}: Pick<StageProps, "folio" | "pending" | "onReview" | "onInspect">) {
  const evidence = folio.evidence_change;
  if (!evidence) return null;
  const label = (item: string) =>
    folio.contract?.allowed_conditions?.find(
      (condition) => condition.id === item,
    )?.label ?? item;
  return (
    <section className="evidence-change">
      <div className="evidence-change-top">
        <span className="eyebrow">
          <Search size={13} />
          TAVILY · {evidence.source ? "RETRIEVED EVIDENCE" : "RETRIEVAL RECORD"}
        </span>
        <Pill
          tone={
            evidence.status === "accepted"
              ? "teal"
              : evidence.status === "proposed"
                ? "ochre"
                : "neutral"
          }
        >
          {evidence.status === "proposed"
            ? "Your decision required"
            : words(evidence.status)}
        </Pill>
      </div>
      <h3>{evidence.assumption ?? "A source-linked change to the schedule"}</h3>
      {evidence.source ? (
        <div className="retrieved-source">
          <ExternalSource url={evidence.source.url}>
            {evidence.source.title}
          </ExternalSource>
          {evidence.source.excerpt ? (
            <blockquote>“{evidence.source.excerpt}”</blockquote>
          ) : null}
          <span className="fine-print">
            Retrieved {dateTime(evidence.queried_at)} · Source text is treated
            as evidence, never as instructions.
          </span>
        </div>
      ) : null}
      <div className="evidence-diff">
        <div>
          <span className="eyebrow">BEFORE RETRIEVAL</span>
          <ul>
            {(evidence.before ?? []).map((item, index) => (
              <li key={`${item}-${index}`}>
                <span className="diff-mark">−</span>
                {label(item)}
              </li>
            ))}
          </ul>
          {!evidence.before?.length ? (
            <p>Original registered schedule</p>
          ) : null}
        </div>
        <div>
          <span className="eyebrow">PROPOSED AFTER RETRIEVAL</span>
          <ul>
            {(evidence.after ?? []).map((item, index) => (
              <li key={`${item}-${index}`}>
                <span className="diff-mark">+</span>
                {label(item)}
              </li>
            ))}
          </ul>
          {!evidence.after?.length ? <p>No schedule change proposed</p> : null}
        </div>
      </div>
      {evidence.explanation ? (
        <p className="evidence-explanation">{evidence.explanation}</p>
      ) : null}
      {evidence.status === "proposed" ? (
        <div className="evidence-decision">
          <p>
            Acceptance changes the actual exploration schedule within the locked
            allowed lattice.
          </p>
          <div className="button-row">
            <Button
              tone="primary"
              disabled={Boolean(pending) || isActive(folio)}
              icon={<Check size={16} />}
              onClick={() => onReview("accept_evidence")}
            >
              Review & accept change
            </Button>
            <Button
              disabled={Boolean(pending) || isActive(folio)}
              onClick={() => onReview("reject_evidence")}
            >
              Decline with a reason
            </Button>
          </div>
        </div>
      ) : (
        <div className="evidence-decision-record">
          <CheckCheck size={16} />
          <span>
            {evidence.status === "accepted"
              ? "Accepted change is applied to the active schedule."
              : evidence.status === "rejected"
                ? "Declined change is preserved in the evidence record."
                : "Recorded as context; no experimental change is claimed."}
          </span>
          <button className="text-button" onClick={() => onInspect("review")}>
            Decision record <ArrowUpRight size={14} />
          </button>
        </div>
      )}
      <details className="query-details">
        <summary>Inspect retrieval query</summary>
        <p className="mono">{evidence.query ?? "Query not returned"}</p>
        <span className="fine-print">
          Receipt {evidence.receipt_id ?? "not available"}
        </span>
      </details>
    </section>
  );
}

export function ChallengeStage(props: StageProps) {
  const { label: providerLabel } = useProviderStatus();
  const {
    folio,
    pending,
    selectedCondition,
    onSelectCondition,
    onAction,
    onReview,
    onInspect,
    onNavigate,
  } = props;
  const discovery = folio.observations.filter(
    (observation) => observation.phase === "discovery",
  );
  const original = folio.observations.find(
    (observation) => observation.phase === "reproduction",
  );
  const selected =
    discovery.find(
      (observation) => observation.condition_id === selectedCondition,
    ) ??
    (selectedCondition === "original" && discovery.length
      ? original
      : undefined) ??
    discovery[0];
  const busy = isActive(folio) || Boolean(pending);
  const accepted = reproductionAccepted(folio);
  const evidencePending = folio.evidence_change?.status === "proposed";
  const plotted = [
    ...(original ? [original] : []),
    ...discovery.filter(
      (observation) => observation.condition_id !== "original",
    ),
  ];
  const proposals = [...(folio.proposals ?? [])].sort(
    (a, b) => a.rank - b.rank,
  );
  return (
    <>
      <StageTitle
        number="03"
        eyebrow="THE CHALLENGE COMPOSER"
        title="Which assumption matters?"
        description="Follow primary-source evidence into a finite, interpretable challenge. Discovery can guide the question; it cannot answer the confirmation test."
      />
      {!accepted ? (
        <Notice title="Reproduction review comes first" tone="ochre">
          Accept the original comparison before retrieving a schedule change or
          starting discovery.
          <div className="notice-action">
            <Button onClick={() => onNavigate("reproduction")} arrow>
              Review reproduction
            </Button>
          </div>
        </Notice>
      ) : null}
      <section>
        <SectionHeading
          number="01"
          title="Let evidence inform the experiment"
        />
        {folio.evidence_change ? (
          <EvidenceChangeView
            folio={folio}
            pending={pending}
            onReview={onReview}
            onInspect={onInspect}
          />
        ) : (
          <div className="retrieval-empty">
            <div className="retrieval-glyph" aria-hidden="true">
              <Search size={27} />
              <span>↗</span>
            </div>
            <div>
              <h3>A source can change the experiment.</h3>
              <p>
                Retrieve primary-source context for the declared assumptions.
                Inspect the proposed before → after change, then decide whether
                it belongs in the active schedule.
              </p>
              <Button
                icon={<Search size={16} />}
                disabled={!accepted || busy || discovery.length > 0}
                busy={pending === "retrieve"}
                onClick={() => void onAction("retrieve")}
              >
                Retrieve source evidence
              </Button>
              <p className="provider-disclosure">
                Tavily retrieves primary sources. The trusted adapter proposes a
                change within the permitted lattice. {providerLabel}
                ranks released discovery results later. Sealed labels are
                excluded.
              </p>
            </div>
          </div>
        )}
      </section>
      <section>
        <SectionHeading
          number="02"
          title={
            discovery.length
              ? "The observed landscape"
              : "Explore the declared lattice"
          }
        >
          <span className="mono">
            {activeConditionIds(folio).filter((id) => id !== "original").length}{" "}
            active variations
          </span>
        </SectionHeading>
        {discovery.length ? (
          <>
            <EffectPlot
              folio={folio}
              observations={plotted}
              selected={selected?.condition_id}
              onSelect={onSelectCondition}
              title="Every tested condition stays visible."
            />
            <ConditionAtlas
              folio={folio}
              selected={selected?.condition_id ?? null}
              onSelect={onSelectCondition}
            />
          </>
        ) : (
          <>
            <p className="section-intro">
              Both methods receive the same training data, preprocessing
              permissions, seeds, and tuning budget. The only changes are the
              declared conditions in the active schedule.
            </p>
            <ConditionAtlas
              folio={folio}
              selected={null}
              onSelect={onSelectCondition}
            />
            <div className="explore-action">
              <Button
                tone="primary"
                icon={<FlaskConical size={16} />}
                disabled={
                  !accepted ||
                  busy ||
                  evidencePending ||
                  Boolean(folio.run?.can_resume)
                }
                busy={pending === "explore"}
                onClick={() => void onAction("explore")}
              >
                Run finite discovery
              </Button>
              <div>
                {evidencePending ? (
                  <p>Accept or decline the proposed evidence change first.</p>
                ) : (
                  <p>The schedule is finite. No condition is added silently.</p>
                )}
                <span className="fine-print">
                  Observed discovery aggregates are sent to {providerLabel}
                  to rank valid condition IDs. Raw rows and confirmation labels
                  are excluded.
                </span>
              </div>
            </div>
          </>
        )}
      </section>
      {discovery.length ? (
        <section>
          <SectionHeading
            number="03"
            title="The model’s proposed next question"
          >
            <button
              className="text-button"
              onClick={() => onInspect("computation")}
            >
              Ranking receipt <ArrowUpRight size={14} />
            </button>
          </SectionHeading>
          {proposals.length ? (
            <div className="proposal-list">
              {proposals.map((proposal) => (
                <article
                  key={proposal.condition_id}
                  className={
                    selected?.condition_id === proposal.condition_id
                      ? "proposal-row proposal-row-selected"
                      : "proposal-row"
                  }
                >
                  <span className="proposal-rank">
                    {String(proposal.rank).padStart(2, "0")}
                  </span>
                  <div>
                    <h3>{conditionLabel(folio, proposal.condition_id)}</h3>
                    <p>{proposal.rationale}</p>
                    {proposal.expected_information ? (
                      <p className="proposal-expectation">
                        <span>Expected information</span>
                        {proposal.expected_information}
                      </p>
                    ) : null}
                    <ScopePill
                      scope={
                        proposal.scope ??
                        folio.contract?.allowed_conditions?.find(
                          (condition) => condition.id === proposal.condition_id,
                        )?.scope
                      }
                    />
                  </div>
                  <Button
                    tone="quiet"
                    disabled={
                      !discovery.some(
                        (observation) =>
                          observation.condition_id === proposal.condition_id,
                      )
                    }
                    onClick={() => onSelectCondition(proposal.condition_id)}
                  >
                    Inspect <ArrowUpRight size={14} />
                  </Button>
                </article>
              ))}
            </div>
          ) : isActive(folio) && folio.run?.action === "explore" ? (
            <Notice title="NVIDIA ranking is pending" tone="blue">
              Discovery measurements are committed. NVIDIA Nemotron is ranking
              the released aggregates; no ranking failure is assumed while this
              operation is active. You can inspect the observed conditions as
              the ranking finishes.
            </Notice>
          ) : (
            <Notice
              title="No validated model ranking is available"
              tone="ochre"
            >
              {folio.planner_error ? <p>{folio.planner_error}</p> : null}The
              measured conditions remain selectable. Inspect a condition below
              and register it yourself; a ranking failure does not erase
              computed evidence.
            </Notice>
          )}
        </section>
      ) : null}
      {selected ? (
        <>
          <SelectedCondition
            folio={folio}
            observation={selected}
            onInspect={() => onInspect("computation")}
          />
          {folio.registration ? (
            <NextStep
              eyebrow="CONFIRMATION IS ALREADY REGISTERED"
              title={conditionLabel(folio, folio.registration.condition_id)}
            >
              <Button
                tone="primary"
                onClick={() => onNavigate("confirmation")}
                arrow
              >
                Inspect registered confirmation
              </Button>
            </NextStep>
          ) : (
            <div className="registration-callout">
              <div>
                <span className="eyebrow">
                  ONE OBSERVED CONDITION · ONE REGISTERED ANALYSIS
                </span>
                <h2>Freeze the choice and its analysis.</h2>
                <p>
                  Register{" "}
                  <strong>
                    {conditionLabel(folio, selected.condition_id)}
                  </strong>{" "}
                  for confirmation. Registration fixes the choice before this
                  folio starts evaluation. Previously exposed labels remain a
                  replay, not a fresh test.
                </p>
              </div>
              <Button
                tone="primary"
                icon={<LockKeyhole size={16} />}
                disabled={busy}
                onClick={() =>
                  onReview("register_confirmation", selected.condition_id)
                }
              >
                Register selected condition
              </Button>
              <p className="fine-print">
                Registration does not start confirmation. You will launch that
                operation separately.
              </p>
            </div>
          )}
        </>
      ) : null}
    </>
  );
}

function VerifierChecks({
  folio,
  onInspect,
}: {
  folio: Folio;
  onInspect: () => void;
}) {
  const verification = folio.verification;
  if (!verification) return null;
  return (
    <section className="verifier-section">
      <SectionHeading number="03" title="An independent computation">
        <Pill tone={verification.status === "verified" ? "teal" : "error"}>
          {verification.status === "verified"
            ? "Bundle verified"
            : "Bundle rejected"}
        </Pill>
      </SectionHeading>
      <RichText
        value={verification.method}
        fallback="Verifier methodology is available in the evidence artifact."
      />
      <ul className="verifier-checks">
        {verification.checks.map((check, index) => (
          <li key={`${check.name}-${index}`}>
            <span className={check.passed ? "check-passed" : "check-failed"}>
              {check.passed ? <Check size={16} /> : <span>×</span>}
            </span>
            <div>
              <strong>{words(check.name)}</strong>
              {check.detail ? <p>{check.detail}</p> : null}
            </div>
            <span className="check-label">
              {check.passed ? "Passed" : "Rejected"}
            </span>
          </li>
        ))}
      </ul>
      <div className="verifier-independence">
        <ShieldCheck size={18} />
        <RichText
          value={verification.independence}
          fallback="The trusted verifier recomputes the metric from immutable predictions and sealed labels. This is computational separation, not independent scientific review."
        />
      </div>
      <Hash value={verification.sha256} label="Verifier SHA-256" />
      <div className="artifact-row">
        <ArtifactLink sha={verification.artifact_sha256}>
          Verifier evidence
        </ArtifactLink>
        <button className="text-button" onClick={onInspect}>
          Inspect computation <ArrowUpRight size={14} />
        </button>
      </div>
    </section>
  );
}

export function ConfirmationStage(props: StageProps) {
  const {
    folio,
    pending,
    selectedCondition,
    onAction,
    onReview,
    onInspect,
    onNavigate,
  } = props;
  const registration = folio.registration;
  const confirmed = folio.observations.filter(
    (observation) => observation.phase === "confirmation",
  );
  const busy = isActive(folio) || Boolean(pending);
  const selection = folio.observations.find(
    (observation) =>
      observation.phase === "discovery" &&
      observation.condition_id === selectedCondition,
  );
  const predictionReady = Boolean(folio.prediction_manifest);
  const replay = registration?.holdout_status === "reproducibility_replay";
  return (
    <>
      <StageTitle
        number="04"
        eyebrow={
          replay
            ? "REGISTERED REPRODUCIBILITY REPLAY"
            : "THE REGISTERED CONFIRMATION"
        }
        title={
          replay
            ? "Registered reproducibility replay"
            : "One question. A held-out answer."
        }
        description={
          replay
            ? "This repeats the registered condition and locked analysis on labels previously used in this workspace. It checks reproducibility; it provides no fresh held-out sample or new confirmatory evidence."
            : "Freeze a discovered condition, compute its predictions once, and let the trusted verifier join sealed labels and apply the locked decision rule."
        }
      />
      <ol className="confirmation-steps" aria-label="Confirmation sequence">
        <li className={registration ? "step-done" : "step-current"}>
          <span>{registration ? <Check size={15} /> : "1"}</span>
          <div>
            <strong>Register</strong>
            <small>Freeze one question</small>
          </div>
        </li>
        <li
          className={
            predictionReady || folio.verification
              ? "step-done"
              : registration
                ? "step-current"
                : ""
          }
        >
          <span>
            {predictionReady || folio.verification ? <Check size={15} /> : "2"}
          </span>
          <div>
            <strong>Predict</strong>
            <small>{replay ? "Recorded partition" : "Sealed evaluation"}</small>
          </div>
        </li>
        <li
          className={
            folio.verification
              ? "step-done"
              : predictionReady
                ? "step-current"
                : ""
          }
        >
          <span>{folio.verification ? <Check size={15} /> : "3"}</span>
          <div>
            <strong>Verify</strong>
            <small>Recompute independently</small>
          </div>
        </li>
      </ol>
      {!registration ? (
        <section className="unrun-state">
          <LockKeyhole size={32} strokeWidth={1.3} />
          <h2>The confirmation question is not registered.</h2>
          <p>
            Choose one observed discovery condition. Registration freezes its
            identity, analysis, and reserved holdout before confirmation begins.
          </p>
          {selection ? (
            <Button
              tone="primary"
              disabled={busy}
              icon={<LockKeyhole size={16} />}
              onClick={() =>
                onReview("register_confirmation", selection.condition_id)
              }
            >
              Register {conditionLabel(folio, selection.condition_id)}
            </Button>
          ) : (
            <Button
              tone="primary"
              onClick={() => onNavigate("challenge")}
              arrow
            >
              Choose a discovery condition
            </Button>
          )}
        </section>
      ) : (
        <>
          <section className="registration-sheet">
            <div className="registration-corners" aria-hidden="true" />
            <div className="registration-sheet-header">
              <span className="eyebrow">
                {replay
                  ? "REPLAY OF PREVIOUSLY REGISTERED EVIDENCE"
                  : "REGISTERED BEFORE HOLDOUT USE"}
              </span>
              <LockKeyhole size={18} />
            </div>
            <h2>{conditionLabel(folio, registration.condition_id)}</h2>
            <ScopePill
              scope={
                folio.contract?.allowed_conditions?.find(
                  (condition) => condition.id === registration.condition_id,
                )?.scope
              }
            />
            <dl>
              <div>
                <dt>Registered by</dt>
                <dd>{registration.reviewer_name ?? "Local operator"}</dd>
              </div>
              <div>
                <dt>Registration time</dt>
                <dd>{dateTime(registration.registered_at)}</dd>
              </div>
              <div>
                <dt>Holdout state</dt>
                <dd>
                  {registration.holdout_status
                    ? words(registration.holdout_status)
                    : "See the computation record"}
                </dd>
              </div>
              {replay ? (
                <div>
                  <dt>Prior evidence</dt>
                  <dd>
                    Labels previously used
                    {registration.prior_folio_id ? (
                      <a
                        className="text-link"
                        href={`?folio=${encodeURIComponent(registration.prior_folio_id)}&stage=folio&inspect=review`}
                      >
                        Inspect prior folio{" "}
                        {registration.prior_folio_id.slice(0, 8)}{" "}
                        <ArrowUpRight size={13} />
                      </a>
                    ) : null}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>Analysis</dt>
                <dd>
                  <RichText value={registration.analysis} />
                </dd>
              </div>
            </dl>
            <Hash value={registration.sha256} label="Registration SHA-256" />
          </section>
          {!folio.verification ? (
            <section className="confirmation-action">
              <div>
                <span className="eyebrow">
                  {predictionReady
                    ? "PREDICTIONS COMMITTED"
                    : "THE NEXT OPERATION"}
                </span>
                <h2>
                  {predictionReady
                    ? "Let the verifier recompute the evidence."
                    : replay
                      ? "Recompute the registered predictions."
                      : "Compute the registered predictions."}
                </h2>
                <p>
                  {replay
                    ? "This uses the same registered analysis and previously exposed labels. The verifier checks reproducibility and recomputes the recorded evidence; this is not a fresh confirmation test."
                    : predictionReady
                      ? "The verifier checks coverage, duplicates, hashes, and the locked protocol, then joins sealed labels to recompute the metric and decision."
                      : "The prediction worker receives the reserved features. The registered question stays fixed; the trusted verifier alone joins the sealed labels."}
                </p>
              </div>
              {predictionReady ? (
                <Button
                  tone="primary"
                  icon={<ShieldCheck size={16} />}
                  disabled={busy}
                  busy={pending === "verify"}
                  onClick={() => void onAction("verify")}
                >
                  Run independent verifier
                </Button>
              ) : (
                <Button
                  tone="primary"
                  icon={<FlaskConical size={16} />}
                  disabled={
                    busy ||
                    folio.status !== "confirmation_locked" ||
                    Boolean(folio.run?.can_resume)
                  }
                  busy={pending === "confirm"}
                  onClick={() => void onAction("confirm")}
                >
                  {replay
                    ? "Run registered replay"
                    : "Start registered confirmation"}
                </Button>
              )}
              <p className="fine-print">
                {replay
                  ? "The prior label exposure remains recorded. Replaying does not reset the scientific evidence."
                  : "An inconclusive result is retained with the same evidence record as any other outcome."}
              </p>
            </section>
          ) : null}
          {confirmed.length ? (
            <>
              <EffectPlot
                folio={folio}
                observations={confirmed}
                title="The registered condition, independently measured."
              />
              {confirmed[0] ? (
                <ResultStats folio={folio} observation={confirmed[0]} />
              ) : null}
            </>
          ) : null}
          <VerifierChecks
            folio={folio}
            onInspect={() => onInspect("computation")}
          />
          {folio.conclusion ? (
            <section
              className={`conclusion-preview outcome-${folio.conclusion.outcome}`}
            >
              <span className="eyebrow">
                MECHANICAL DECISION · {outcomeLabel(folio.conclusion.outcome)}
              </span>
              <h2>{folio.conclusion.title}</h2>
              <p>{folio.conclusion.statement}</p>
              {folio.status === "review_ready" ? (
                <Button
                  tone="primary"
                  icon={<ClipboardCheck size={16} />}
                  disabled={busy}
                  onClick={() => onReview("review_conclusion")}
                >
                  Review bounded conclusion
                </Button>
              ) : (
                <Button
                  tone="primary"
                  onClick={() => onNavigate("folio")}
                  arrow
                >
                  Read the evidence folio
                </Button>
              )}
            </section>
          ) : null}
        </>
      )}
    </>
  );
}

function ArgumentRow({
  number,
  title,
  children,
  onClick,
  link,
}: {
  number: string;
  title: string;
  children: React.ReactNode;
  onClick: () => void;
  link: string;
}) {
  return (
    <article className="argument-row">
      <span className="argument-number">{number}</span>
      <div>
        <h3>{title}</h3>
        {children}
        <button className="text-button" onClick={onClick}>
          {link}
          <ArrowUpRight size={14} />
        </button>
      </div>
    </article>
  );
}

function LimitationSummary({
  folio,
  limitations,
}: {
  folio: Folio;
  limitations: string[];
}) {
  const hasUnestablishedIndependence = limitations.some((note) =>
    /independence.*unestablished|unestablished.*independence/i.test(note),
  );
  const groups = [
    {
      title: "Tested scope",
      test: /authored|paper|generaliz|discovery|historically|contamin|dataset/i,
      summary:
        folio.adapter_id === "occupancy"
          ? "One authored comparison on one room’s data. Discovery precedes training; paper-protocol fidelity and broader generalization are unqualified."
          : "A controlled synthetic experiment. Its result stays tied to the declared data generator and tested conditions.",
    },
    {
      title: "Uncertainty",
      test: /interval|independen.*block|independen.*day|calendar|usable|holm|equivalence|seeds/i,
      summary: hasUnestablishedIndependence
        ? "Adjacent-day independence is unestablished. Intervals are descriptive; the result does not establish equivalence."
        : "The block-level analysis and declared comparison family bound the inference. Seeds remain repeated fits, not independent replications.",
    },
    {
      title: "Scientific qualification",
      test: /methodologist|participant|benchmark|review|qualif/i,
      summary:
        "External scientific review, participant research, and a frozen multi-case benchmark remain pending.",
    },
    {
      title: "Execution boundary",
      test: /adapter|subprocess|sandbox|OS identity|arbitrary|code|execute/i,
      summary:
        "Trusted local adapters run in separate processes under the same OS identity. This is not a security sandbox.",
    },
  ];
  const entries = groups
    .map((group) => ({
      ...group,
      count: limitations.filter((note) => group.test.test(note)).length,
    }))
    .filter((group) => group.count);
  return (
    <>
      <ol className="limitation-summary">
        {entries.map((group, index) => (
          <li key={group.title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <h3>{group.title}</h3>
              <p>{group.summary}</p>
            </div>
          </li>
        ))}
      </ol>
      <details className="full-record">
        <summary>
          Read the complete limitation record{" "}
          <span className="mono">{limitations.length} entries</span>
        </summary>
        <ol>
          {limitations.map((note, index) => (
            <li key={`${index}-${note}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{note}</p>
            </li>
          ))}
        </ol>
      </details>
    </>
  );
}

function ArtifactManifest({ folio }: { folio: Folio }) {
  const artifacts = folio.artifacts ?? [];
  const counts = new Map<string, number>();
  for (const artifact of artifacts) {
    const kind = artifact.kind ?? artifact.media_type;
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
  }
  return (
    <div className="artifact-manifest">
      <div className="artifact-summary">
        <div>
          <span className="eyebrow">THE CONTENT-ADDRESSED RECORD</span>
          <p>
            <strong>{artifacts.length}</strong> evidence artifacts
          </p>
        </div>
        <div className="artifact-summary-types">
          {[...counts].map(([kind, count]) => (
            <span key={kind}>
              {words(kind)} <b>{count}</b>
            </span>
          ))}
        </div>
      </div>
      <details className="full-record artifact-record">
        <summary>
          Inspect the complete artifact manifest{" "}
          <span className="mono">{artifacts.length} files</span>
        </summary>
        <div className="artifact-list">
          {artifacts.map((artifact, index) => (
            <div
              className="artifact-list-row"
              key={`${artifact.sha256}-${index}`}
            >
              <FileText size={16} />
              <div>
                <strong>{artifact.name}</strong>
                <span>
                  {artifact.kind ? words(artifact.kind) : artifact.media_type} ·{" "}
                  {bytes(artifact.bytes)}
                </span>
              </div>
              <code title={artifact.sha256}>{hashShort(artifact.sha256)}</code>
              <ArtifactLink sha={artifact.sha256}>Open</ArtifactLink>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}

export function FolioStage(props: StageProps) {
  const { folio, pending, onReview, onInspect, onNavigate } = props;
  const conclusion = folio.conclusion;
  const original = folio.observations.find(
    (observation) => observation.phase === "reproduction",
  );
  const confirmed = folio.observations.filter(
    (observation) => observation.phase === "confirmation",
  );
  const allLimitations = [
    ...new Set([
      ...(conclusion?.limitations ?? []),
      ...(folio.limitations ?? []),
    ]),
  ];
  if (!conclusion)
    return (
      <>
        <StageTitle
          number="05"
          eyebrow="THE EVIDENCE FOLIO"
          title="A conclusion needs evidence."
          description="The folio assembles a bounded answer from the reviewed contract, observed results, registration, and independent verifier."
        />
        <div className="unrun-state">
          <FileText size={35} strokeWidth={1.3} />
          <h2>The evidence argument is still open.</h2>
          <p>
            No confirmed conclusion has been computed. Continue from the last
            recorded stage; all available source and computation records remain
            inspectable.
          </p>
          <Button
            tone="primary"
            onClick={() =>
              onNavigate(folio.stage === "folio" ? "confirmation" : folio.stage)
            }
            arrow
          >
            Continue the research
          </Button>
        </div>
        <SourceFootnote folio={folio} onInspect={() => onInspect("source")} />
      </>
    );
  const checks = folio.verification?.checks ?? [];
  return (
    <>
      <header className={`folio-verdict outcome-${conclusion.outcome}`}>
        <div className="stage-kicker">
          <span className="eyebrow">
            {folio.registration?.holdout_status === "reproducibility_replay"
              ? "REPRODUCIBILITY REPLAY · EVIDENCE FOLIO"
              : "THE EVIDENCE FOLIO"}
          </span>
          <span className="folio-page">
            05<span>/05</span>
          </span>
        </div>
        <div className="verdict-meta">
          <Pill
            tone={
              conclusion.outcome === "inconclusive"
                ? "ochre"
                : conclusion.outcome === "boundary_identified"
                  ? "rust"
                  : conclusion.outcome === "supported_in_tested_scope"
                    ? "teal"
                    : "blue"
            }
          >
            {outcomeLabel(conclusion.outcome)}
          </Pill>
          <span className="mono">
            CONTRACT v{folio.contract?.revision ?? "—"}
          </span>
        </div>
        <h1>{conclusion.title}</h1>
        <p className="verdict-statement">{conclusion.statement}</p>
        <div className="verdict-scope">
          <span className="eyebrow">THE SCOPE OF THIS ANSWER</span>
          <RichText
            value={
              conclusion.scope &&
              typeof conclusion.scope === "object" &&
              !Array.isArray(conclusion.scope) &&
              typeof conclusion.scope.population === "string"
                ? conclusion.scope.population
                : conclusion.scope
            }
          />
          <div className="scope-human-metadata">
            <span>
              <strong>Condition</strong>
              {folio.registration
                ? conditionLabel(folio, folio.registration.condition_id)
                : "Not registered"}
            </span>
            <span>
              <strong>Superiority threshold</strong>
              {effect(folio.contract?.practical_delta)} pp
            </span>
          </div>
        </div>
        <div className="verdict-footer">
          {folio.verification?.status === "verified" ? (
            <span>
              <ShieldCheck size={17} />
              Independent computation verified
            </span>
          ) : (
            <span>
              <FileText size={17} />
              Verification {folio.verification?.status ?? "pending"}
            </span>
          )}
          <button
            className="text-button"
            onClick={() => onInspect("computation")}
          >
            Inspect the evidence <ArrowUpRight size={14} />
          </button>
        </div>
      </header>
      <SourceFootnote folio={folio} onInspect={() => onInspect("source")} />
      {confirmed.length ? (
        <EffectPlot
          folio={folio}
          observations={[...(original ? [original] : []), ...confirmed]}
          title="The claim, measured in its conditions."
        />
      ) : null}
      {confirmed[0] ? (
        <ResultStats folio={folio} observation={confirmed[0]} />
      ) : null}
      <section>
        <SectionHeading number="01" title="Follow the evidence argument" />
        <div className="argument-list">
          <ArgumentRow
            number="S1"
            title="A precise, authored comparison"
            onClick={() => onInspect("source")}
            link="Inspect source & provenance"
          >
            <p>“{folio.contract?.claim ?? folio.claim}”</p>
            <p className="fine-print">
              {folio.adapter_id === "occupancy"
                ? "A local authored comparison on UCI Occupancy data. Paper-protocol matching remains unqualified."
                : "A labeled controlled synthetic experiment. It is not an empirical discovery in a published paper."}
            </p>
          </ArgumentRow>
          <ArgumentRow
            number="C1"
            title="A contract fixed before testing"
            onClick={() => onInspect("data")}
            link="Inspect split & contract"
          >
            <p>
              {folio.contract?.candidate?.name ?? "Candidate"} versus{" "}
              {folio.contract?.baseline?.name ?? "baseline"}, using{" "}
              {words(
                folio.contract?.metric ?? "balanced_accuracy",
              ).toLowerCase()}
              . The declared practical margin is{" "}
              {effect(folio.contract?.practical_delta)} percentage points.
            </p>
            <RichText value={folio.contract?.split} />
          </ArgumentRow>
          <ArgumentRow
            number="R1"
            title={
              folio.registration?.holdout_status === "reproducibility_replay"
                ? "The original question, registered for replay"
                : "A question registered before its answer"
            }
            onClick={() => onInspect("review")}
            link="Inspect registration & decisions"
          >
            <p>
              {folio.registration
                ? `${conditionLabel(folio, folio.registration.condition_id)} was registered at ${dateTime(folio.registration.registered_at)} by ${folio.registration.reviewer_name ?? "the local operator"}.`
                : "No confirmation registration is recorded."}
            </p>
            {folio.registration?.holdout_status === "reproducibility_replay" ? (
              <p className="replay-provenance">
                Confirmation labels were previously used.{" "}
                {folio.registration.prior_folio_id ? (
                  <a
                    href={`?folio=${encodeURIComponent(folio.registration.prior_folio_id)}&stage=folio&inspect=review`}
                  >
                    Inspect prior folio{" "}
                    {folio.registration.prior_folio_id.slice(0, 8)}{" "}
                    <ArrowUpRight size={13} />
                  </a>
                ) : (
                  "No fresh held-out sample is claimed."
                )}
              </p>
            ) : null}
            {folio.evidence_change ? (
              <p className="fine-print">
                Retrieved evidence was{" "}
                {folio.evidence_change.status.replaceAll("_", " ")}. Its before
                → after proposal remains in the review record.
              </p>
            ) : null}
          </ArgumentRow>
          <ArgumentRow
            number="V1"
            title="The metric recomputed from evidence"
            onClick={() => onInspect("computation")}
            link="Inspect verifier & receipts"
          >
            <p>
              {checks.length
                ? `${checks.filter((check) => check.passed).length} of ${checks.length} mechanical checks passed.`
                : "No mechanical check list is available."}{" "}
              {textValue(folio.verification?.independence)}
            </p>
            {confirmed[0]?.warning ? (
              <RichText
                value={confirmed[0].warning}
                className="scientific-warning"
              />
            ) : null}
          </ArgumentRow>
        </div>
      </section>
      <section className="limitations-section">
        <SectionHeading number="02" title="What remains open" />
        {allLimitations.length ? (
          <LimitationSummary folio={folio} limitations={allLimitations} />
        ) : (
          <p>
            See the locked scope and verifier record before generalizing this
            result.
          </p>
        )}
      </section>
      <section>
        <SectionHeading number="03" title="Operator review" />
        {conclusion.review ? (
          <ReviewStamp
            name={reviewName(conclusion.review)}
            timestamp={reviewDate(conclusion.review)}
            note={reviewNote(conclusion.review)}
            label="BOUNDED CONCLUSION ACKNOWLEDGED BY LOCAL OPERATOR"
          />
        ) : (
          <div className="review-callout">
            <h3>A local review is still needed.</h3>
            <p>
              Read the conclusion and its limits before recording your
              acknowledgement. This does not substitute for external scientific
              sign-off.
            </p>
            <Button
              tone="primary"
              icon={<ClipboardCheck size={16} />}
              disabled={
                Boolean(pending) ||
                isActive(folio) ||
                folio.status !== "review_ready"
              }
              onClick={() => onReview("review_conclusion")}
            >
              Review bounded conclusion
            </Button>
          </div>
        )}
      </section>
      <section className="export-section">
        <SectionHeading number="04" title="Evidence you can take with you" />
        <p className="section-intro">
          The report follows the argument. The evidence bundle preserves its
          inputs, configuration, predictions, hashes, and independent rerun
          path.
        </p>
        <div className="export-actions">
          <a
            className="button button-primary"
            href={exportUrl(folio.id, "report")}
            target="_blank"
            rel="noreferrer"
          >
            <FileText size={17} />
            Open readable report
            <ArrowUpRight size={16} />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
          <a
            className="button button-secondary"
            href={exportUrl(folio.id, "export")}
            download
          >
            <FileArchive size={17} />
            Download evidence bundle
          </a>
        </div>
        <ArtifactManifest folio={folio} />
      </section>
      <footer className="folio-endnote">
        <span className="registration-plus" aria-hidden="true">
          +
        </span>
        <span>Evidence stays useful when its limits stay visible.</span>
        <span className="registration-plus" aria-hidden="true">
          +
        </span>
      </footer>
    </>
  );
}

export function StageContent(props: StageProps & { stage: Stage }) {
  switch (props.stage) {
    case "contract":
      return <ContractStage {...props} />;
    case "reproduction":
      return <ReproductionStage {...props} />;
    case "challenge":
      return <ChallengeStage {...props} />;
    case "confirmation":
      return <ConfirmationStage {...props} />;
    case "folio":
      return <FolioStage {...props} />;
  }
}
