import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  CircleAlert,
  FileArchive,
  FileText,
  Fingerprint,
  LibraryBig,
  LockKeyhole,
  RefreshCw,
  X,
} from "lucide-react";
import { api, ApiError, exportUrl } from "./api";
import { dateTime, isActive, words } from "./format";
import { CreateDialog, ReviewDialog, ScopeDialog } from "./dialogs";
import { Inspector } from "./Inspector";
import { Library } from "./Library";
import { StageContent } from "./stages";
import { ProviderContext, providerStatus } from "./provider";
import { WheatWorkspace } from "./WheatWorkspace";
import type { ReviewAction } from "./stages";
import type {
  Action,
  AdapterId,
  Folio,
  FolioSummary,
  Health,
  InspectorTab,
  Route,
  Stage,
} from "./types";
import {
  BusyPage,
  Button,
  Dialog,
  IconButton,
  Mark,
  Pill,
  RunBanner,
} from "./ui";

const stageOrder: Stage[] = [
  "contract",
  "reproduction",
  "challenge",
  "confirmation",
  "folio",
];
const inspectorTabs: InspectorTab[] = [
  "source",
  "data",
  "computation",
  "review",
  "activity",
];
const stageCopy: Record<Stage, { title: string; caption: string }> = {
  contract: { title: "Contract", caption: "Define the claim" },
  reproduction: { title: "Reproduction", caption: "Establish the comparison" },
  challenge: { title: "Challenge", caption: "Test an assumption" },
  confirmation: { title: "Confirmation", caption: "Register, then verify" },
  folio: { title: "Evidence folio", caption: "Read the bounded answer" },
};

function readRoute(): Route {
  const query = new URLSearchParams(window.location.search);
  const stage = query.get("stage") as Stage | null;
  const inspector = query.get("inspect") as InspectorTab | null;
  return {
    folio: query.get("folio"),
    stage: stage && stageOrder.includes(stage) ? stage : "contract",
    inspector:
      inspector && inspectorTabs.includes(inspector) ? inspector : "source",
    condition: query.get("condition"),
  };
}

function normalize(folio: Folio): Folio {
  return {
    ...folio,
    source: folio.source ?? null,
    contract: folio.contract ?? null,
    run: folio.run ?? null,
    evidence_change: folio.evidence_change ?? null,
    observations: folio.observations ?? [],
    proposals: folio.proposals ?? [],
    registration: folio.registration ?? null,
    verification: folio.verification ?? null,
    conclusion: folio.conclusion ?? null,
    receipts: folio.receipts ?? [],
    events: folio.events ?? [],
    artifacts: folio.artifacts ?? [],
    limitations: folio.limitations ?? [],
  };
}

function useWideInspector() {
  const [wide, setWide] = useState(
    () => window.matchMedia("(min-width: 1500px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1500px)");
    const update = () => setWide(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return wide;
}

const actionAnnouncements: Partial<Record<Action, string>> = {
  update_contract: "Contract revision saved.",
  lock_contract: "Contract locked. The reproduction can begin.",
  accept_reproduction: "Reproduction review recorded.",
  accept_evidence:
    "Evidence change accepted and applied to the exploration schedule.",
  reject_evidence: "Evidence change declined; the decision is recorded.",
  register_confirmation:
    "Condition registered. Confirmation remains a separate operation.",
  review_conclusion: "Local conclusion review recorded.",
  cancel: "Cancellation requested. Waiting for the operation to stop safely.",
  resume: "Saved operation is resuming.",
};

const isHistoryRoute = () => {
  const query = new URLSearchParams(window.location.search);
  return query.has("folio") || query.get("view") === "history";
};

export default function App() {
  const [history, setHistory] = useState(isHistoryRoute);
  useEffect(() => {
    const back = () => setHistory(isHistoryRoute());
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  const openHistory = () => {
    window.history.pushState(
      {},
      "",
      `${window.location.pathname}?view=history`,
    );
    setHistory(true);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  return history ? <LegacyApp /> : <WheatWorkspace onHistory={openHistory} />;
}

function LegacyApp() {
  const [route, setRoute] = useState<Route>(readRoute);
  const [folios, setFolios] = useState<FolioSummary[]>([]);
  const [folio, setFolio] = useState<Folio | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [loadingFolio, setLoadingFolio] = useState(false);
  const [connected, setConnected] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [pollWarning, setPollWarning] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [pollVersion, setPollVersion] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [createAdapter, setCreateAdapter] = useState<AdapterId | null>(null);
  const [review, setReview] = useState<{
    action: ReviewAction;
    condition?: string;
  } | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const mutationRef = useRef(false);
  const folioRef = useRef<Folio | null>(null);
  const mainRef = useRef<HTMLElement>(null);
  const wide = useWideInspector();
  useEffect(() => {
    folioRef.current = folio;
  }, [folio]);

  const navigate = useCallback((patch: Partial<Route>, replace = false) => {
    setRoute((current) => {
      const next = { ...current, ...patch };
      const query = new URLSearchParams();
      if (next.folio) {
        query.set("folio", next.folio);
        query.set("stage", next.stage);
        query.set("inspect", next.inspector);
        if (next.condition) query.set("condition", next.condition);
      } else query.set("view", "history");
      const nextUrl = `${window.location.pathname}${query.size ? `?${query}` : ""}`;
      if (nextUrl !== `${window.location.pathname}${window.location.search}`)
        window.history[replace ? "replaceState" : "pushState"]({}, "", nextUrl);
      return next;
    });
  }, []);

  const refreshLibrary = useCallback(async () => {
    try {
      const result = await api.folios();
      setFolios(result.folios ?? []);
      setConnected(true);
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure
          : new ApiError({
              code: "library_unavailable",
              message:
                "The local library could not be read. Reconnect and refresh.",
            }),
      );
      setConnected(false);
    } finally {
      setLoadingLibrary(false);
    }
  }, []);

  useEffect(() => {
    void refreshLibrary();
    void api
      .health()
      .then((nextHealth) => {
        setHealth(nextHealth);
        setConnected(true);
      })
      .catch(() => setConnected(false));
    const back = () => setRoute(readRoute());
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, [refreshLibrary]);

  useEffect(() => {
    if (!route.folio) {
      setFolio(null);
      setLoadingFolio(false);
      setPollWarning(false);
      return;
    }
    const id = route.folio;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoadingFolio(true);
    setFolio((current) => (current?.id === id ? current : null));
    async function poll(initial: boolean) {
      let delay = 5000;
      try {
        const next = normalize(await api.folio(id));
        if (!alive) return;
        setFolio((current) =>
          current?.id === next.id && current.revision > next.revision
            ? current
            : next,
        );
        setConnected(true);
        setPollWarning(false);
        delay = isActive(next) ? 1500 : 8000;
        if (initial) setError(null);
      } catch (failure) {
        if (!alive) return;
        setConnected(false);
        setPollWarning(true);
        if (initial)
          setError(
            failure instanceof ApiError
              ? failure
              : new ApiError({
                  code: "folio_unavailable",
                  message:
                    "This folio could not be opened. Return to the library or refresh the saved record.",
                }),
          );
      } finally {
        if (alive) {
          setLoadingFolio(false);
          timer = setTimeout(() => void poll(false), delay);
        }
      }
    }
    void poll(true);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [route.folio, pollVersion]);

  useEffect(() => {
    document.title =
      folio && route.folio
        ? `${folio.title} — Crucible`
        : "Crucible — Follow the evidence.";
  }, [folio?.title, route.folio]);

  useEffect(() => {
    if (!route.folio) return;
    window.scrollTo({ top: 0, behavior: "instant" });
    requestAnimationFrame(() =>
      mainRef.current?.focus({ preventScroll: true }),
    );
  }, [route.folio, route.stage]);

  function updateSaved(next: Folio) {
    const normalized = normalize(next);
    folioRef.current = normalized;
    setFolio((current) =>
      current?.id === normalized.id && current.revision > normalized.revision
        ? current
        : normalized,
    );
    setFolios((current) =>
      current.some((item) => item.id === normalized.id)
        ? current.map((item) => (item.id === normalized.id ? normalized : item))
        : [normalized, ...current],
    );
  }

  const runAction = useCallback(
    async (
      action: Action,
      body: Record<string, unknown> = {},
      nextStage?: Stage,
    ) => {
      const current = folioRef.current;
      if (!current || mutationRef.current) return false;
      mutationRef.current = true;
      setPending(action);
      setError(null);
      try {
        const next = normalize(await api.action(current, action, body));
        updateSaved(next);
        setConnected(true);
        setPollVersion((currentVersion) => currentVersion + 1);
        setAnnouncement(
          actionAnnouncements[action] ??
            `${words(action)} started. The operation will report durable checkpoints.`,
        );
        if (nextStage) navigate({ stage: nextStage });
        return true;
      } catch (failure) {
        const apiError =
          failure instanceof ApiError
            ? failure
            : new ApiError({
                code: "action_failed",
                message:
                  "The action could not be completed. Refresh the saved record before trying again.",
              });
        setError(apiError);
        if (/revision|conflict|stale|session/.test(apiError.code)) {
          try {
            updateSaved(await api.folio(current.id));
          } catch {
            /* Keep the last durable response visible. */
          }
        }
        return false;
      } finally {
        mutationRef.current = false;
        setPending(null);
      }
    },
    [navigate],
  );

  async function create(body: {
    adapter_id: AdapterId;
    title?: string;
    claim?: string;
  }) {
    if (mutationRef.current) return false;
    mutationRef.current = true;
    setPending("create");
    setError(null);
    try {
      const next = normalize(await api.create(body));
      updateSaved(next);
      setCreateAdapter(null);
      setConnected(true);
      setAnnouncement(
        "Research folio created. Source and split preparation will report real checkpoints.",
      );
      navigate({
        folio: next.id,
        stage: next.stage ?? "contract",
        condition: null,
        inspector: "source",
      });
      return true;
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure
          : new ApiError({
              code: "create_failed",
              message: "The folio could not be created. Please try again.",
            }),
      );
      return false;
    } finally {
      mutationRef.current = false;
      setPending(null);
    }
  }

  function inspect(tab: InspectorTab) {
    navigate({ inspector: tab });
    setInspectorOpen(true);
    if (wide)
      requestAnimationFrame(() =>
        document
          .querySelector<HTMLElement>(".inspector-content")
          ?.focus({ preventScroll: true }),
      );
  }

  function library() {
    navigate({ folio: null, stage: "contract", condition: null });
    setInspectorOpen(false);
    setError(null);
    void refreshLibrary();
  }
  const chosenFolio = folio && folio.id === route.folio ? folio : null;
  const discovery =
    chosenFolio?.observations.filter(
      (observation) => observation.phase === "discovery",
    ) ?? [];
  const selectedCondition =
    route.condition ??
    chosenFolio?.registration?.condition_id ??
    chosenFolio?.proposals?.find((proposal) =>
      discovery.some(
        (observation) => observation.condition_id === proposal.condition_id,
      ),
    )?.condition_id ??
    discovery[0]?.condition_id ??
    null;
  const onOpen = (summary: FolioSummary) => {
    setError(null);
    navigate({
      folio: summary.id,
      stage:
        summary.status === "complete" || summary.conclusion
          ? "folio"
          : (summary.stage ?? "contract"),
      condition: null,
    });
  };
  const reviewNext: Record<ReviewAction, Stage> = {
    lock_contract: "reproduction",
    accept_reproduction: "challenge",
    accept_evidence: "challenge",
    reject_evidence: "challenge",
    register_confirmation: "confirmation",
    review_conclusion: "folio",
  };

  return (
    <ProviderContext.Provider value={providerStatus(health)}>
      <a className="skip-link" href="#main-content">
        Skip to the research
      </a>
      <header className="masthead">
        <button
          className="wordmark"
          onClick={library}
          aria-label="Crucible home"
        >
          <Mark small />
          <span>
            Crucible<span className="wordmark-period">.</span>
          </span>
        </button>
        <div className="masthead-divider" />
        <button className="workspace-switch" onClick={library}>
          <span>LOCAL WORKSPACE</span>
          <ChevronDown size={13} />
        </button>
        {route.folio ? (
          <div className="masthead-folio">
            <span>/</span>
            <span>{chosenFolio?.title ?? "Opening folio"}</span>
          </div>
        ) : null}
        <nav className="masthead-actions" aria-label="Workspace actions">
          {route.folio ? (
            <>
              <button className="header-library" onClick={library}>
                <LibraryBig size={16} />
                <span>Library</span>
              </button>
              <Button
                tone="quiet"
                className="inspector-trigger"
                icon={<Fingerprint size={17} />}
                onClick={() => inspect(route.inspector)}
              >
                Evidence trail
              </Button>
              {chosenFolio ? <ExportMenu folio={chosenFolio} /> : null}
            </>
          ) : (
            <>
              <span className="masthead-private">
                <LockKeyhole size={13} />
                Private
              </span>
              <Button
                tone="quiet"
                icon={<BookOpen size={16} />}
                onClick={() => setScopeOpen(true)}
              >
                About the scope
              </Button>
            </>
          )}
        </nav>
      </header>
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
      {error ? (
        <div className="global-error" role="alert">
          <CircleAlert size={19} />
          <div>
            <strong>{error.message}</strong>
            <span>
              {error.code.replaceAll("_", " ")}
              {error.recoverable ? " · Saved evidence can be recovered." : ""}
            </span>
          </div>
          <Button
            tone="quiet"
            icon={<RefreshCw size={15} />}
            onClick={() => {
              setError(null);
              if (chosenFolio)
                void api
                  .folio(chosenFolio.id)
                  .then(updateSaved)
                  .catch((failure) => setError(failure));
              else void refreshLibrary();
            }}
          >
            Refresh saved record
          </Button>
          <IconButton label="Dismiss error" onClick={() => setError(null)}>
            <X size={17} />
          </IconButton>
        </div>
      ) : null}
      {!route.folio ? (
        <Library
          folios={folios}
          loading={loadingLibrary}
          connected={connected}
          onOpen={onOpen}
          onCreate={(adapter) => {
            setError(null);
            setCreateAdapter(adapter);
          }}
          onScope={() => setScopeOpen(true)}
        />
      ) : chosenFolio ? (
        <div className={`workbench ${wide ? "workbench-with-inspector" : ""}`}>
          <StageRail
            folio={chosenFolio}
            stage={route.stage}
            onStage={(stage) => navigate({ stage })}
            onLibrary={library}
            onScope={() => setScopeOpen(true)}
          />
          <main
            className="research-main"
            id="main-content"
            tabIndex={-1}
            ref={mainRef}
          >
            <div className="folio-meta-strip">
              <div>
                <span className="meta-folio-label">FOLIO</span>
                <code>{chosenFolio.id.slice(0, 8).toUpperCase()}</code>
                <span className="meta-divider">/</span>
                <span>
                  {chosenFolio.adapter_id === "synthetic"
                    ? "CONTROLLED SYNTHETIC"
                    : "AUTHORED · PUBLIC DATA"}
                </span>
              </div>
              <span className="meta-updated">
                Updated {dateTime(chosenFolio.updated_at)}
              </span>
            </div>
            {pollWarning ? (
              <div className="poll-warning" role="status">
                <CircleAlert size={15} />
                <span>
                  Connection interrupted. Showing the last saved record;
                  reconnecting automatically.
                </span>
              </div>
            ) : null}
            <RunBanner
              folio={chosenFolio}
              pending={pending}
              onAction={(action) => void runAction(action)}
              onInspect={() => inspect("activity")}
            />
            <article className="research-sheet">
              <StageContent
                stage={route.stage}
                folio={chosenFolio}
                pending={pending}
                selectedCondition={selectedCondition}
                onSelectCondition={(condition) => {
                  setError(null);
                  navigate({ condition });
                }}
                onAction={runAction}
                onReview={(action, condition) => {
                  setError(null);
                  setReview({ action, condition });
                }}
                onInspect={inspect}
                onNavigate={(stage) => navigate({ stage })}
              />
            </article>
            <footer className="research-footer">
              <span>
                CRUCIBLE <i> / </i> FOLLOW THE EVIDENCE.
              </span>
              <button
                className="text-button"
                onClick={() => inspect("activity")}
              >
                Activity ledger <ArrowUpRight size={13} />
              </button>
            </footer>
          </main>
          {wide ? (
            <Inspector
              folio={chosenFolio}
              tab={route.inspector}
              selectedCondition={selectedCondition}
              onTab={(tab) => navigate({ inspector: tab })}
            />
          ) : null}
        </div>
      ) : loadingFolio ? (
        <BusyPage />
      ) : (
        <main className="missing-folio" id="main-content">
          <CircleAlert size={32} strokeWidth={1.3} />
          <h1>The folio could not be opened.</h1>
          <p>
            The local API may still be starting, or this folio may no longer be
            available.
          </p>
          <Button
            tone="primary"
            onClick={library}
            icon={<ArrowLeft size={16} />}
          >
            Return to the library
          </Button>
        </main>
      )}
      {chosenFolio && !wide && inspectorOpen ? (
        <Dialog
          open
          onDismiss={() => setInspectorOpen(false)}
          title="Evidence trail"
          eyebrow="SOURCE → COMPUTATION"
          className="inspector-dialog"
        >
          <Inspector
            folio={chosenFolio}
            tab={route.inspector}
            selectedCondition={selectedCondition}
            onTab={(tab) => navigate({ inspector: tab })}
            embedded
          />
        </Dialog>
      ) : null}
      {createAdapter ? (
        <CreateDialog
          key={createAdapter}
          adapter={createAdapter}
          pending={pending === "create"}
          error={error?.message}
          onDismiss={() => {
            setCreateAdapter(null);
            setError(null);
          }}
          onCreate={create}
        />
      ) : null}
      {review && chosenFolio ? (
        <ReviewDialog
          key={`${review.action}-${review.condition ?? ""}`}
          folio={chosenFolio}
          action={review.action}
          condition={review.condition}
          pending={pending === review.action}
          error={error?.message}
          onDismiss={() => {
            setReview(null);
            setError(null);
          }}
          onSubmit={async (body) => {
            const success = await runAction(
              review.action,
              body,
              reviewNext[review.action],
            );
            if (success) setReview(null);
            return success;
          }}
        />
      ) : null}
      {scopeOpen ? <ScopeDialog onDismiss={() => setScopeOpen(false)} /> : null}
    </ProviderContext.Provider>
  );
}

function ExportMenu({ folio }: { folio: Folio }) {
  return (
    <details className="export-menu">
      <summary className="button button-secondary" aria-label="Export evidence">
        <ArrowDownToLine size={15} />
        <span>Export</span>
        <ChevronDown size={13} />
      </summary>
      <div className="export-dropdown">
        <span className="eyebrow">PORTABLE EVIDENCE</span>
        <a
          href={exportUrl(folio.id, "report")}
          target="_blank"
          rel="noreferrer"
        >
          <FileText size={16} />
          <span>Readable HTML report</span>
          <ArrowUpRight size={14} />
        </a>
        {folio.verification ? (
          <a href={exportUrl(folio.id, "export")} download>
            <FileArchive size={16} />
            <span>Rerunnable evidence bundle</span>
            <ArrowDownToLine size={14} />
          </a>
        ) : (
          <p>
            <LockKeyhole size={15} />
            <span>
              The ZIP bundle becomes available after independent verification.
            </span>
          </p>
        )}
      </div>
    </details>
  );
}

function StageRail({
  folio,
  stage,
  onStage,
  onLibrary,
  onScope,
}: {
  folio: Folio;
  stage: Stage;
  onStage: (stage: Stage) => void;
  onLibrary: () => void;
  onScope: () => void;
}) {
  const complete = (item: Stage) =>
    item === "contract"
      ? Boolean(folio.contract?.locked)
      : item === "reproduction"
        ? Boolean(folio.reproduction_accepted)
        : item === "challenge"
          ? folio.observations.some(
              (observation) => observation.phase === "discovery",
            )
          : item === "confirmation"
            ? Boolean(folio.verification)
            : folio.status === "complete";
  return (
    <aside className="stage-rail">
      <div className="rail-top">
        <button className="rail-back text-button" onClick={onLibrary}>
          <ArrowLeft size={14} />
          All folios
        </button>
        <span className="eyebrow">THE EVIDENCE PATH</span>
      </div>
      <nav className="stage-navigation" aria-label="Research stages">
        {stageOrder.map((item, index) => (
          <button
            key={item}
            className={`stage-button ${stage === item ? "stage-button-active" : ""}`}
            onClick={() => onStage(item)}
            aria-current={stage === item ? "step" : undefined}
          >
            <span
              className={`stage-number ${complete(item) ? "stage-number-complete" : ""}`}
            >
              {complete(item) ? (
                <Check size={13} />
              ) : (
                String(index + 1).padStart(2, "0")
              )}
            </span>
            <span className="stage-button-label">
              <strong>{stageCopy[item].title}</strong>
              <small>{stageCopy[item].caption}</small>
            </span>
            {stage === item ? (
              <ArrowRight size={14} className="stage-active-arrow" />
            ) : null}
          </button>
        ))}
      </nav>
      <div className="rail-footer">
        <Pill
          tone={
            isActive(folio)
              ? "blue"
              : folio.status === "complete"
                ? "teal"
                : "neutral"
          }
        >
          {isActive(folio) ? "Operation in progress" : words(folio.status)}
        </Pill>
        <div className="rail-adapter">
          <span className="eyebrow">TRUSTED ADAPTER</span>
          <strong>
            {folio.adapter_id === "synthetic"
              ? "Synthetic control"
              : "UCI Occupancy"}
          </strong>
          <p>Supervised tabular classification</p>
        </div>
        <button className="text-button" onClick={onScope}>
          Scope & limitations <ArrowUpRight size={13} />
        </button>
        <span className="rail-private">
          <LockKeyhole size={12} />
          Private local workspace
        </span>
      </div>
    </aside>
  );
}
