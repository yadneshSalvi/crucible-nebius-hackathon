import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  FlaskConical,
  LockKeyhole,
  Plus,
} from "lucide-react";
import { date, outcomeLabel, words } from "./format";
import type { AdapterId, FolioSummary } from "./types";
import { Button, Mark, Pill } from "./ui";

export function Library({
  folios,
  loading,
  connected,
  onOpen,
  onCreate,
  onScope,
}: {
  folios: FolioSummary[];
  loading: boolean;
  connected: boolean;
  onOpen: (folio: FolioSummary) => void;
  onCreate: (adapter: AdapterId) => void;
  onScope: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const filtered = folios.filter(
    (folio) =>
      filter === "all" ||
      (filter === "pending"
        ? !folio.conclusion && !folio.outcome
        : (folio.conclusion?.outcome ?? folio.outcome) === filter),
  );
  return (
    <main className="library" id="main-content" tabIndex={-1}>
      <section className="library-hero">
        <div className="library-hero-main">
          <p className="eyebrow">
            <span className="tiny-cross">+</span>THE COMPUTATIONAL EVIDENCE
            WORKBENCH
          </p>
          <h1>
            A claim is only
            <br />
            the <em>beginning.</em>
          </h1>
          <p className="library-intro">
            Put an assumption to the test. See what survives.
            <br className="desktop-break" /> Keep the evidence—and its
            limits—within reach.
          </p>
          <div className="library-hero-actions">
            <Button
              tone="primary"
              icon={<Plus size={17} />}
              onClick={() => onCreate("occupancy")}
            >
              Start a research folio
            </Button>
            <button className="text-button" onClick={onScope}>
              Explore the supported scope <ArrowUpRight size={15} />
            </button>
          </div>
        </div>
        <aside className="library-principle" aria-label="How Crucible works">
          <div className="principle-stamp">
            <Mark />
            <span>
              FOLLOW
              <br />
              THE EVIDENCE.
            </span>
            <span className="principle-cross">+</span>
          </div>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Make it precise.</strong>
                <p>A reviewed contract before the first fit.</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Change one assumption.</strong>
                <p>A finite challenge, with uncertainty intact.</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Know what the answer means.</strong>
                <p>An independently computed, bounded conclusion.</p>
              </div>
            </li>
          </ol>
        </aside>
      </section>
      <section className="folio-library" aria-labelledby="library-heading">
        <div className="library-toolbar">
          <div>
            <span className="eyebrow">YOUR RESEARCH</span>
            <h2 id="library-heading">
              Evidence folios{" "}
              <span>{folios.length.toString().padStart(2, "0")}</span>
            </h2>
          </div>
          <div className="library-controls">
            <label className="sr-only" htmlFor="outcome-filter">
              Filter by scientific outcome
            </label>
            <select
              id="outcome-filter"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">All outcomes</option>
              <option value="pending">Awaiting evidence</option>
              <option value="inconclusive">Inconclusive</option>
              <option value="supported_in_tested_scope">
                Supported in scope
              </option>
              <option value="boundary_identified">
                Applicability boundary
              </option>
              <option value="evidence_against_registered_claim">
                Evidence against
              </option>
            </select>
            <Button
              tone="quiet"
              icon={<Plus size={16} />}
              onClick={() => onCreate("occupancy")}
            >
              New folio
            </Button>
          </div>
        </div>
        {loading && !folios.length ? (
          <div className="library-loading" role="status">
            <BookOpen size={24} strokeWidth={1.3} />
            <p>Reading the local folio library…</p>
          </div>
        ) : filtered.length ? (
          <div className="folio-rows">
            {filtered.map((folio, index) => {
              const outcome = folio.conclusion?.outcome ?? folio.outcome;
              return (
                <article className="folio-row" key={folio.id}>
                  <button
                    className="folio-row-open"
                    onClick={() => onOpen(folio)}
                  >
                    <span className="folio-row-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="folio-row-content">
                      <span className="folio-row-type">
                        <span>
                          {folio.adapter_id === "synthetic" ||
                          folio.case_kind === "controlled_synthetic"
                            ? "CONTROLLED SYNTHETIC"
                            : "AUTHORED · PUBLIC DATA"}
                        </span>
                        <span>SUPERVISED CLASSIFICATION</span>
                      </span>
                      <span className="folio-row-title">{folio.title}</span>
                      <span className="folio-row-claim">{folio.claim}</span>
                    </span>
                    <span className="folio-row-status">
                      <Pill
                        tone={
                          outcome === "inconclusive"
                            ? "ochre"
                            : outcome === "supported_in_tested_scope"
                              ? "teal"
                              : outcome === "boundary_identified"
                                ? "rust"
                                : folio.status === "running"
                                  ? "blue"
                                  : "neutral"
                        }
                      >
                        {outcome
                          ? outcomeLabel(outcome)
                          : folio.status === "running"
                            ? "Operation running"
                            : folio.status === "complete"
                              ? "Complete"
                              : "Awaiting evidence"}
                      </Pill>
                      <span>
                        {words(folio.stage)} ·{" "}
                        {date(folio.updated_at ?? folio.created_at)}
                      </span>
                      <span className="folio-row-review">
                        {folio.conclusion?.review
                          ? "Local conclusion review recorded"
                          : "External scientific qualification pending"}
                      </span>
                    </span>
                    <ArrowUpRight
                      className="folio-row-arrow"
                      size={24}
                      strokeWidth={1.25}
                    />
                  </button>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="library-empty">
            <div className="empty-folio-glyph" aria-hidden="true">
              <span>+</span>
              <BookOpen size={32} strokeWidth={1.1} />
              <span>+</span>
            </div>
            <div>
              <h3>
                {folios.length
                  ? "No folios match this outcome."
                  : "Give your first claim a place to be tested."}
              </h3>
              <p>
                {folios.length
                  ? "Change the outcome filter to inspect the rest of the library."
                  : "Start with the authored UCI Occupancy comparison, or inspect the safeguards with a clearly labeled synthetic case."}
              </p>
              <div className="button-row">
                {folios.length ? (
                  <Button onClick={() => setFilter("all")}>
                    Show all folios
                  </Button>
                ) : (
                  <>
                    <Button
                      tone="primary"
                      onClick={() => onCreate("occupancy")}
                      arrow
                    >
                      Start the public-data comparison
                    </Button>
                    <Button
                      icon={<FlaskConical size={15} />}
                      onClick={() => onCreate("synthetic")}
                    >
                      Create synthetic case
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
      <section className="library-scope-note">
        <span className="scope-note-label">
          <LockKeyhole size={15} />
          PRIVATE LOCAL WORKSPACE
        </span>
        <p>
          Trusted tabular adapters, reviewed contracts, real computation.
          <br />
          Paper and repository imports remain outside the supported local scope.
        </p>
        <button className="text-button" onClick={onScope}>
          Read the scope <ArrowRight size={14} />
        </button>
      </section>
      <footer className="library-footer">
        <span>
          CRUCIBLE <i> / </i> A scientific argument, open to inspection.
        </span>
        <span className="connection-state">
          <i className={connected ? "connected" : ""} />
          {connected ? "Local API connected" : "Local API unavailable"}
        </span>
      </footer>
    </main>
  );
}
