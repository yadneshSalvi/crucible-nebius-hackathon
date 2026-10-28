import { useState } from "react";
import { useProviderStatus } from "./provider";
import {
  ArrowRight,
  Check,
  ClipboardCheck,
  FlaskConical,
  LockKeyhole,
} from "lucide-react";
import { conditionLabel, effect, textValue } from "./format";
import type { AdapterId, Folio } from "./types";
import type { ReviewAction } from "./stages";
import { Button, Dialog, InlineError, Notice, Pill } from "./ui";

export function CreateDialog({
  adapter,
  pending,
  error,
  onDismiss,
  onCreate,
}: {
  adapter: AdapterId;
  pending: boolean;
  error?: string;
  onDismiss: () => void;
  onCreate: (body: {
    adapter_id: AdapterId;
    title?: string;
    claim?: string;
  }) => Promise<boolean>;
}) {
  const [selected, setSelected] = useState<AdapterId>(adapter);
  const [title, setTitle] = useState("");
  const [claim, setClaim] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await onCreate({
      adapter_id: selected,
      ...(title.trim() ? { title: title.trim() } : {}),
      ...(claim.trim() ? { claim: claim.trim() } : {}),
    });
  }
  return (
    <Dialog
      open
      onDismiss={onDismiss}
      title="Give the claim a folio."
      eyebrow="A NEW RESEARCH ARGUMENT"
      className="create-dialog"
    >
      <form onSubmit={(event) => void submit(event)}>
        <InlineError message={error} title="The folio could not be created" />
        <fieldset className="adapter-fieldset">
          <legend className="field-label">
            Choose a trusted experiment adapter
          </legend>
          <label
            className={`adapter-option ${selected === "occupancy" ? "adapter-selected" : ""}`}
          >
            <input
              type="radio"
              name="adapter"
              value="occupancy"
              checked={selected === "occupancy"}
              onChange={() => setSelected("occupancy")}
            />
            <span className="adapter-choice-icon">
              <Check size={14} />
            </span>
            <span>
              <strong>UCI Occupancy</strong>
              <span>
                Random forest vs. logistic regression on public sensor data.
              </span>
              <Pill tone="blue">Authored comparison · CC BY 4.0 data</Pill>
            </span>
          </label>
          <label
            className={`adapter-option ${selected === "synthetic" ? "adapter-selected" : ""}`}
          >
            <input
              type="radio"
              name="adapter"
              value="synthetic"
              checked={selected === "synthetic"}
              onChange={() => setSelected("synthetic")}
            />
            <span className="adapter-choice-icon">
              <Check size={14} />
            </span>
            <span>
              <strong>Controlled synthetic case</strong>
              <span>
                A labeled control to inspect the workflow and verifier
                safeguards.
              </span>
              <Pill tone="purple">Synthetic · not a paper discovery</Pill>
            </span>
          </label>
        </fieldset>
        <label className="field-label" htmlFor="new-title">
          Folio title <span>optional</span>
        </label>
        <input
          id="new-title"
          minLength={3}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Use the adapter’s authored title"
          maxLength={120}
          disabled={pending}
        />
        <label className="field-label" htmlFor="new-claim">
          Claim <span>optional · editable before locking</span>
        </label>
        <textarea
          id="new-claim"
          minLength={20}
          value={claim}
          onChange={(event) => setClaim(event.target.value)}
          rows={3}
          maxLength={800}
          placeholder="Use the authored comparison, or state a claim within this adapter’s fixed methods and metric."
          disabled={pending}
        />
        <Notice title="Source and split preparation are real operations">
          Creating a folio prepares the pinned data and a discovery/confirmation
          plan before fitting. No model call is made until you request one.
        </Notice>
        <div className="dialog-actions">
          <Button type="button" onClick={onDismiss} disabled={pending}>
            Cancel
          </Button>
          <Button type="submit" tone="primary" busy={pending} arrow>
            Create research folio
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function storedName(): string {
  try {
    const stored = JSON.parse(
      localStorage.getItem("crucible.operator.v1") ?? "null",
    ) as { version?: number; name?: string } | null;
    return stored?.version === 1 && typeof stored.name === "string"
      ? stored.name
      : "";
  } catch {
    return "";
  }
}

const reviewCopy: Record<
  ReviewAction,
  { title: string; button: string; description: string }
> = {
  lock_contract: {
    title: "Review the contract before the first fit.",
    button: "Record review & lock contract",
    description:
      "Check the authored claim, practical margin, population, split, and finite allowed challenge space. Approval covers the authored claim and trusted numerical specification; it does not endorse model-supplied assumptions. Locking binds later results to this revision.",
  },
  accept_reproduction: {
    title: "Review the original comparison.",
    button: "Accept reproduction review",
    description:
      "Check the actual computation and its uncertainty against the locked authored protocol. This does not certify reproduction of the linked paper.",
  },
  accept_evidence: {
    title: "Accept a specific evidence change.",
    button: "Accept & apply schedule change",
    description:
      "This decision applies the source-linked change to the real exploration schedule, within the locked allowed lattice. The immutable contract remains preserved.",
  },
  reject_evidence: {
    title: "Keep the original exploration schedule.",
    button: "Record decision & decline change",
    description:
      "The source and proposed change stay in the folio. State why the change should not alter the experiment.",
  },
  register_confirmation: {
    title: "Register one condition and its analysis.",
    button: "Register condition for confirmation",
    description:
      "Registration commits one observed condition and the locked analysis. If this workspace already used the same labels and analysis, this becomes a reproducibility replay; it does not create fresh held-out evidence. You will launch computation separately.",
  },
  review_conclusion: {
    title: "Review the answer and its limits.",
    button: "Acknowledge bounded conclusion",
    description:
      "Read the computed decision, tested scope, uncertainty, and outstanding limitations. This records a local operator acknowledgement.",
  },
};

export function ReviewDialog({
  folio,
  action,
  condition,
  pending,
  error,
  onDismiss,
  onSubmit,
}: {
  folio: Folio;
  action: ReviewAction;
  condition?: string;
  pending: boolean;
  error?: string;
  onDismiss: () => void;
  onSubmit: (body: Record<string, unknown>) => Promise<boolean>;
}) {
  const [name, setName] = useState(storedName);
  const [note, setNote] = useState("");
  const copy = reviewCopy[action];
  const requiresNote = [
    "lock_contract",
    "accept_evidence",
    "reject_evidence",
    "review_conclusion",
  ].includes(action);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const body: Record<string, unknown> = { reviewer_name: name.trim() };
    if (requiresNote)
      body[
        action === "accept_evidence" || action === "reject_evidence"
          ? "reason"
          : "review_note"
      ] = note.trim();
    if (action === "register_confirmation") body.condition_id = condition;
    if (await onSubmit(body)) {
      try {
        localStorage.setItem(
          "crucible.operator.v1",
          JSON.stringify({ version: 1, name: name.trim() }),
        );
      } catch {
        /* Review remains on the server if local storage is unavailable. */
      }
    }
  }
  return (
    <Dialog
      open
      onDismiss={onDismiss}
      title={copy.title}
      eyebrow="LOCAL OPERATOR REVIEW"
      className="review-dialog"
    >
      <p className="dialog-description">{copy.description}</p>
      <InlineError message={error} title="The review could not be recorded" />
      {action === "lock_contract" ? (
        <div className="review-context">
          <span className="eyebrow">
            CONTRACT v{folio.contract?.revision ?? "—"}
          </span>
          <p>“{folio.contract?.claim ?? folio.claim}”</p>
          <span className="mono">
            Practical margin {effect(folio.contract?.practical_delta)} pp
          </span>
        </div>
      ) : action === "register_confirmation" ? (
        <div className="review-context">
          <span className="eyebrow">THE ONE REGISTERED CONDITION</span>
          <h3>
            {condition
              ? conditionLabel(folio, condition)
              : "No condition selected"}
          </h3>
          <p>{textValue(folio.contract?.analysis)}</p>
          <span className="fine-print">
            This condition freezes when you register it. It cannot be swapped
            for this folio’s confirmation test.
          </span>
        </div>
      ) : action === "review_conclusion" ? (
        <div className="review-context">
          <span className="eyebrow">THE BOUNDED CONCLUSION</span>
          <h3>{folio.conclusion?.title}</h3>
          <p>{folio.conclusion?.statement}</p>
          <p className="fine-print">{textValue(folio.conclusion?.scope)}</p>
        </div>
      ) : action === "accept_evidence" || action === "reject_evidence" ? (
        <div className="review-context">
          <span className="eyebrow">SOURCE-LINKED ASSUMPTION</span>
          <p>{folio.evidence_change?.assumption}</p>
          <span className="fine-print">
            {folio.evidence_change?.explanation}
          </span>
        </div>
      ) : null}
      <form onSubmit={(event) => void submit(event)}>
        <label className="field-label" htmlFor="reviewer-name">
          Your name
        </label>
        <input
          id="reviewer-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={100}
          autoComplete="name"
          placeholder="The local reviewer’s name"
          disabled={pending}
        />
        {requiresNote ? (
          <>
            <label className="field-label" htmlFor="review-note">
              {action === "accept_evidence" || action === "reject_evidence"
                ? "Reason for this decision"
                : "Review note"}
            </label>
            <textarea
              id="review-note"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              required
              maxLength={2000}
              placeholder={
                action === "review_conclusion"
                  ? "What does this result justify, and what remains uncertain?"
                  : "Record the basis for your review."
              }
              disabled={pending}
            />
          </>
        ) : null}
        <div className="review-role-note">
          <ClipboardCheck size={17} />
          <p>
            This records your decision as the <strong>local operator</strong>.
            External scientific qualification remains pending.
          </p>
        </div>
        <div className="dialog-actions">
          <Button type="button" onClick={onDismiss} disabled={pending}>
            Keep reviewing
          </Button>
          <Button
            type="submit"
            tone="primary"
            icon={
              action === "register_confirmation" ||
              action === "lock_contract" ? (
                <LockKeyhole size={16} />
              ) : (
                <Check size={16} />
              )
            }
            busy={pending}
            disabled={
              !name.trim() ||
              (requiresNote && !note.trim()) ||
              (action === "register_confirmation" && !condition)
            }
          >
            {copy.button}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function ScopeDialog({ onDismiss }: { onDismiss: () => void }) {
  const { label, nebiusQualification } = useProviderStatus();
  return (
    <Dialog
      open
      onDismiss={onDismiss}
      title="A small scope. A complete evidence trail."
      eyebrow="SUPPORTED IN THIS LOCAL WORKBENCH"
      className="scope-dialog"
    >
      <div className="scope-dialog-content">
        <div className="scope-feature">
          <FlaskConical size={23} />
          <div>
            <h3>Trusted tabular classification</h3>
            <p>
              An authored random forest / logistic regression comparison on UCI
              Occupancy data, plus a clearly labeled synthetic control. Both use
              fixed metrics and a finite allowed condition lattice.
            </p>
          </div>
        </div>
        <div className="scope-feature">
          <LockKeyhole size={23} />
          <div>
            <h3>Reviewed and registered</h3>
            <p>
              A local operator locks the contract, accepts reproduction, decides
              on retrieved evidence, and freezes one confirmation question. The
              later holdout does not become another adaptive search.
            </p>
          </div>
        </div>
        <div className="scope-feature">
          <ClipboardCheck size={23} />
          <div>
            <h3>Independent computation, bounded claims</h3>
            <p>
              A trusted verifier recomputes measurements and mechanical checks
              from the evidence bundle. External methodologist review and
              paper-protocol qualification remain pending.
            </p>
          </div>
        </div>
        <Notice title="Paper and repository imports are not supported">
          This local build does not run arbitrary uploaded code, repositories,
          or PDFs. A submitted URL is not a verified protocol; start with a
          trusted adapter and review its declared scope.
        </Notice>
        <p className="fine-print">
          Model proposals use {label}. Retrieval uses Tavily. Nebius route
          qualification: {nebiusQualification}. Actual usage is recorded per
          folio.
        </p>
        <div className="dialog-actions">
          <Button tone="primary" onClick={onDismiss}>
            Return to the workbench <ArrowRight size={16} />
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
