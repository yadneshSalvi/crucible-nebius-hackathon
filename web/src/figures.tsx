import { useEffect, useId, useRef, useState } from "react";
import { ArrowDownToLine, ArrowUpRight, Check, Circle } from "lucide-react";
import {
  activeConditionIds,
  conditionLabel,
  effect,
  finite,
  integer,
  percent,
  scopeLabel,
  textValue,
} from "./format";
import type { Folio, Observation } from "./types";
import { ArtifactLink, ScopePill } from "./ui";

function scaleFor(observations: Observation[], delta: number) {
  const points = observations
    .flatMap((observation) => [
      observation.effect,
      observation.ci_low,
      observation.ci_high,
    ])
    .filter(finite);
  const lower = Math.min(0, ...points);
  const upper = Math.max(delta, 0, ...points);
  const padding = Math.max((upper - lower) * 0.15, 0.008);
  const rawStep = (upper - lower + padding * 2) / 5;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const relative = rawStep / magnitude;
  const step =
    (relative <= 1 ? 1 : relative <= 2 ? 2 : relative <= 5 ? 5 : 10) *
    magnitude;
  const low = Math.floor((lower - padding) / step) * step;
  const high = Math.ceil((upper + padding) / step) * step;
  const ticks = Array.from(
    { length: Math.round((high - low) / step) + 1 },
    (_, index) => low + index * step,
  );
  return { low, high, ticks };
}

export function EffectPlot({
  folio,
  observations,
  selected,
  onSelect,
  title = "The measured difference",
  compact = false,
}: {
  folio: Folio;
  observations: Observation[];
  selected?: string | null;
  onSelect?: (id: string) => void;
  title?: string;
  compact?: boolean;
}) {
  const id = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const [annotationSize, setAnnotationSize] = useState(12.5);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const update = () => {
      const scale = svg.getBoundingClientRect().width / 760;
      if (scale > 0)
        setAnnotationSize((previous) =>
          Math.abs(previous - 12.5 / scale) < 0.01 ? previous : 12.5 / scale,
        );
    };
    const observer = new ResizeObserver(update);
    observer.observe(svg);
    update();
    return () => observer.disconnect();
  }, [observations.length]);
  if (!observations.length) return null;
  const delta = finite(folio.contract?.practical_delta)
    ? folio.contract.practical_delta
    : 0;
  const { low, high, ticks } = scaleFor(observations, delta);
  const width = 760;
  const left = compact ? 150 : 174;
  const right = 66;
  const plotWidth = width - left - right;
  const rowHeight = compact ? 58 : 66;
  const top = 82;
  const bottom = top + observations.length * rowHeight;
  const height = bottom + 63;
  const x = (value: number) =>
    left + ((value - low) / (high - low)) * plotWidth;
  const candidate = folio.contract?.candidate?.name ?? "Candidate";
  const baseline = folio.contract?.baseline?.name ?? "Baseline";
  const select = (conditionId: string) => onSelect?.(conditionId);
  const uniqueUnits = [
    ...new Set(
      observations.map((observation) => observation.unit).filter(Boolean),
    ),
  ];
  const uniqueMethods = [
    ...new Set(
      observations
        .map((observation) => observation.interval_method)
        .filter(Boolean),
    ),
  ];
  return (
    <figure
      className={`effect-figure ${compact ? "effect-figure-compact" : ""}`}
      aria-labelledby={`${id}-caption`}
    >
      <figcaption id={`${id}-caption`} className="figure-caption">
        <div>
          <span className="eyebrow">MEASURED EFFECT</span>
          <h3>{title}</h3>
          <p>Candidate − baseline · balanced accuracy · percentage points</p>
        </div>
        <span className="figure-index">FIG. 01</span>
      </figcaption>
      <div className="plot-legend">
        <span>
          <i className="legend-dot" />
          Observed estimate
        </span>
        <span>
          <i className="legend-line" />
          Descriptive interval
        </span>
        <span>
          <i className="legend-threshold" />
          Superiority threshold {effect(delta)} pp
        </span>
      </div>
      <div
        className="plot-scroll"
        role="region"
        aria-label="Effect plot; the equivalent data table follows"
        tabIndex={0}
      >
        <svg
          ref={svgRef}
          className="effect-svg"
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-labelledby={`${id}-svg-title ${id}-desc`}
        >
          <title id={`${id}-svg-title`}>{title}</title>
          <desc id={`${id}-desc`}>
            Each solid dot is an observed candidate minus baseline difference.
            Horizontal lines show the reported uncertainty. The gray dashed line
            is zero; the ochre dotted line is the positive registered
            superiority threshold.{" "}
            {observations
              .map(
                (observation) =>
                  `${observation.condition_label ?? conditionLabel(folio, observation.condition_id)}: ${effect(observation.effect)} percentage points, interval ${effect(observation.ci_low)} to ${effect(observation.ci_high)}.`,
              )
              .join(" ")}
          </desc>
          <line
            x1={x(delta)}
            x2={x(delta)}
            y1={top - 28}
            y2={bottom - 28}
            className="superiority-threshold"
          />
          {ticks.map((tick, index) => (
            <g key={index}>
              <line
                x1={x(tick)}
                x2={x(tick)}
                y1={top - 28}
                y2={bottom - 28}
                className={Math.abs(tick) < 1e-9 ? "zero-rule" : "plot-grid"}
              />
              <text
                x={x(tick)}
                y={top - 41}
                textAnchor="middle"
                className="axis-number"
              >
                {effect(
                  Math.abs(tick) < 1e-9 ? 0 : tick,
                  Math.abs(high - low) < 0.1 ? 1 : 0,
                )}
              </text>
            </g>
          ))}
          <text x={left} y={19} className="axis-title">
            EFFECT (pp)
          </text>
          <text x={width - 3} y={19} textAnchor="end" className="axis-title">
            ESTIMATE
          </text>
          {observations.map((observation, index) => {
            const y = top + index * rowHeight;
            const label =
              observation.condition_label ??
              conditionLabel(folio, observation.condition_id);
            const selectedRow = selected === observation.condition_id;
            const validInterval =
              finite(observation.ci_low) && finite(observation.ci_high);
            return (
              <g
                key={observation.id}
                className={`plot-row ${selectedRow ? "plot-row-selected" : ""} ${onSelect ? "plot-row-interactive" : ""}`}
                role={onSelect ? "button" : undefined}
                tabIndex={onSelect ? 0 : undefined}
                aria-label={
                  onSelect
                    ? `Inspect ${label}: ${effect(observation.effect)} percentage points`
                    : undefined
                }
                aria-pressed={onSelect ? selectedRow : undefined}
                onClick={() => select(observation.condition_id)}
                onKeyDown={(event) => {
                  if (
                    onSelect &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    event.preventDefault();
                    select(observation.condition_id);
                  }
                }}
              >
                <rect
                  x={0}
                  y={y - 26}
                  width={width}
                  height={rowHeight - 1}
                  className="plot-row-background"
                />
                <text x={6} y={y - 1} className="plot-row-label">
                  {label.length > 25 ? `${label.slice(0, 24)}…` : label}
                </text>
                <text x={6} y={y + 17} className="plot-row-phase">
                  {observation.phase === "confirmation"
                    ? "REGISTERED CONFIRMATION"
                    : observation.phase === "discovery"
                      ? "EXPLORATORY DISCOVERY"
                      : "ORIGINAL CONDITION"}
                </text>
                {validInterval ? (
                  <>
                    <line
                      x1={x(observation.ci_low!)}
                      x2={x(observation.ci_high!)}
                      y1={y}
                      y2={y}
                      className="interval-line"
                    />
                    <line
                      x1={x(observation.ci_low!)}
                      x2={x(observation.ci_low!)}
                      y1={y - 5}
                      y2={y + 5}
                      className="interval-cap"
                    />
                    <line
                      x1={x(observation.ci_high!)}
                      x2={x(observation.ci_high!)}
                      y1={y - 5}
                      y2={y + 5}
                      className="interval-cap"
                    />
                  </>
                ) : (
                  <text x={left + 8} y={y + 19} className="plot-missing">
                    Interval unavailable
                  </text>
                )}
                {finite(observation.effect) ? (
                  <circle
                    cx={x(observation.effect)}
                    cy={y}
                    r={selectedRow ? 6 : 5}
                    className="estimate-dot"
                  />
                ) : (
                  <text x={left + 8} y={y + 2} className="plot-missing">
                    No valid estimate
                  </text>
                )}
                <text
                  x={width - 5}
                  y={y + 4}
                  textAnchor="end"
                  className="estimate-number"
                >
                  {effect(observation.effect)}
                </text>
              </g>
            );
          })}
          <line
            x1={left}
            x2={width - right}
            y1={bottom - 27}
            y2={bottom - 27}
            className="plot-axis"
          />
          <text
            x={left}
            y={bottom + 4}
            className="direction-label"
            style={{ fontSize: annotationSize }}
          >
            ← Favors{" "}
            {baseline.length > 24 ? `${baseline.slice(0, 23)}…` : baseline}
          </text>
          <text
            x={width - right}
            y={bottom + 4}
            textAnchor="end"
            className="direction-label"
            style={{ fontSize: annotationSize }}
          >
            Favors{" "}
            {candidate.length > 24 ? `${candidate.slice(0, 23)}…` : candidate} →
          </text>
          <text
            x={left}
            y={bottom + 30}
            className="axis-note"
            style={{ fontSize: annotationSize }}
          >
            <tspan x={left}>The registered tests compare the effect</tspan>
            <tspan x={left} dy={18}>
              with the positive superiority threshold.
            </tspan>
          </text>
        </svg>
      </div>
      <div className="figure-footnote">
        <p>
          <strong>Analysis unit:</strong>{" "}
          {uniqueUnits.length
            ? uniqueUnits.join("; ")
            : "See the locked analysis plan"}
          .
        </p>
        <p>
          {uniqueMethods.length
            ? uniqueMethods.join("; ")
            : "Interval method is not reported."}
        </p>
        <p>
          Seeds describe training variation. Correlated rows and repeated seeds
          do not add independent datasets.
        </p>
      </div>
      <ObservationTable
        folio={folio}
        observations={observations}
        selected={selected}
        onSelect={onSelect}
      />
    </figure>
  );
}

export function ObservationTable({
  folio,
  observations,
  selected,
  onSelect,
}: {
  folio: Folio;
  observations: Observation[];
  selected?: string | null;
  onSelect?: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(
    () => window.matchMedia("(max-width: 767px)").matches,
  );
  const csv = [
    "condition,phase,candidate,baseline,effect,ci_low,ci_high,usable_blocks,analyzed_rows,predicted_rows",
    ...observations.map((observation) =>
      [
        `"${(observation.condition_label ?? conditionLabel(folio, observation.condition_id)).replaceAll('"', '""')}"`,
        observation.phase,
        observation.candidate ?? "",
        observation.baseline ?? "",
        observation.effect ?? "",
        observation.ci_low ?? "",
        observation.ci_high ?? "",
        observation.blocks ?? "",
        observation.analyzed_rows ?? "",
        observation.rows ?? "",
      ].join(","),
    ),
  ].join("\n");
  const href = `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  return (
    <details
      className="figure-data"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        View the observed values{" "}
        <span className="mono">
          {observations.length}{" "}
          {observations.length === 1 ? "condition" : "conditions"}
        </span>
      </summary>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Observed balanced accuracy data"
      >
        <table className="data-table">
          <caption className="sr-only">
            Actual measurements. Effects and intervals are in percentage points;
            candidate and baseline values are balanced accuracy.
          </caption>
          <thead>
            <tr>
              <th scope="col">Condition</th>
              <th scope="col">Candidate</th>
              <th scope="col">Baseline</th>
              <th scope="col">Effect (pp)</th>
              <th scope="col">Interval (pp)</th>
              <th scope="col">Usable blocks</th>
              <th scope="col">Analyzed / predicted rows</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((observation) => (
              <tr
                key={observation.id}
                className={
                  selected === observation.condition_id
                    ? "selected-table-row"
                    : ""
                }
              >
                <th scope="row">
                  {onSelect ? (
                    <button
                      className="table-select"
                      onClick={() => onSelect(observation.condition_id)}
                    >
                      {observation.condition_label ??
                        conditionLabel(folio, observation.condition_id)}
                      <ArrowUpRight size={13} />
                    </button>
                  ) : (
                    (observation.condition_label ??
                    conditionLabel(folio, observation.condition_id))
                  )}
                </th>
                <td>{percent(observation.candidate)}</td>
                <td>{percent(observation.baseline)}</td>
                <td>{effect(observation.effect)}</td>
                <td>
                  {finite(observation.ci_low) && finite(observation.ci_high)
                    ? `${effect(observation.ci_low)} to ${effect(observation.ci_high)}`
                    : "Unavailable"}
                </td>
                <td>{integer(observation.blocks)}</td>
                <td>
                  {integer(observation.analyzed_rows)} /{" "}
                  {integer(observation.rows)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <a
        className="text-link table-download"
        href={href}
        download="crucible-observed-values.csv"
      >
        <ArrowDownToLine size={14} />
        Download these values (CSV)
      </a>
    </details>
  );
}

export function ResultStats({
  folio,
  observation,
}: {
  folio: Folio;
  observation: Observation;
}) {
  return (
    <dl className="result-stats">
      <div>
        <dt>
          <span className="method-dot candidate-dot" />
          {folio.contract?.candidate?.name ?? "Candidate"}
        </dt>
        <dd>
          {percent(observation.candidate)}
          <span className="stat-caption">balanced accuracy</span>
        </dd>
      </div>
      <div>
        <dt>
          <span className="method-dot baseline-dot" />
          {folio.contract?.baseline?.name ?? "Baseline"}
        </dt>
        <dd>
          {percent(observation.baseline)}
          <span className="stat-caption">balanced accuracy</span>
        </dd>
      </div>
      <div>
        <dt>Paired difference</dt>
        <dd>
          {effect(observation.effect)}
          <small> pp</small>
          <span className="stat-caption">candidate − baseline</span>
        </dd>
      </div>
      <div>
        <dt>Usable blocks</dt>
        <dd>
          {integer(observation.blocks)}
          <span className="stat-caption">
            {integer(observation.analyzed_rows)} analyzed /{" "}
            {integer(observation.rows)} predicted rows
          </span>
        </dd>
      </div>
    </dl>
  );
}

export function SeedSpread({ observation }: { observation: Observation }) {
  const seeds = Array.isArray(observation.seeds) ? observation.seeds : [];
  const values = (observation.seed_effects ?? [])
    .map((entry, index) =>
      typeof entry === "number"
        ? { seed: seeds[index], effect: entry }
        : { seed: entry.seed ?? seeds[index], effect: entry.effect },
    )
    .filter((entry) => finite(entry.effect));
  if (!values.length) return null;
  return (
    <details className="seed-spread">
      <summary>
        Training-seed spread{" "}
        <span className="mono">{values.length} recorded seeds</span>
      </summary>
      <p>
        These are repeated fits on the same data, not independent experimental
        units.
      </p>
      <div className="seed-values">
        {values.map((entry, index) => (
          <div key={`${entry.seed ?? index}`}>
            <span>Seed {entry.seed ?? `#${index + 1}`}</span>
            <strong>
              {effect(entry.effect)}
              <small> pp</small>
            </strong>
          </div>
        ))}
      </div>
    </details>
  );
}

export function ConditionAtlas({
  folio,
  selected,
  onSelect,
}: {
  folio: Folio;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const allowed = folio.contract?.allowed_conditions ?? [];
  const active = activeConditionIds(folio);
  const observed = new Map(
    folio.observations
      .filter((observation) => observation.phase === "discovery")
      .map((observation) => [observation.condition_id, observation]),
  );
  return (
    <div className="condition-atlas">
      <div className="atlas-intro">
        <span className="eyebrow">FINITE CONDITION ATLAS</span>
        <span className="mono">
          {[...observed.keys()].filter((id) => id !== "original").length}{" "}
          observed /{" "}
          {allowed.filter((condition) => condition.id !== "original").length}{" "}
          permitted variations
        </span>
      </div>
      <div className="atlas-rows">
        {allowed
          .filter((condition) => condition.id !== "original")
          .map((condition) => {
            const observation = observed.get(condition.id);
            const rank = folio.proposals?.find(
              (proposal) => proposal.condition_id === condition.id,
            )?.rank;
            return (
              <button
                key={condition.id}
                className={`atlas-row ${selected === condition.id ? "atlas-row-selected" : ""} ${observation ? "atlas-row-observed" : "atlas-row-untested"}`}
                onClick={() => onSelect(condition.id)}
                disabled={!observation}
                aria-pressed={selected === condition.id}
              >
                <span className="atlas-selector">
                  {selected === condition.id ? (
                    <Check size={15} />
                  ) : (
                    <Circle size={15} />
                  )}
                </span>
                <span className="atlas-condition">
                  <strong>{condition.label}</strong>
                  <span>
                    {condition.description ??
                      [
                        condition.feature,
                        finite(condition.rate)
                          ? `${condition.rate * 100}%`
                          : condition.rate,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                  </span>
                </span>
                <span className="atlas-scope">
                  {scopeLabel(condition.scope)}
                  {rank ? <small>Model rank {rank}</small> : null}
                </span>
                <span className="atlas-effect">
                  {observation ? (
                    <>
                      <strong>
                        {effect(observation.effect)}
                        <small> pp</small>
                      </strong>
                      <span>discovery estimate</span>
                    </>
                  ) : (
                    <>
                      <strong>Untested</strong>
                      <span>
                        {active.includes(condition.id)
                          ? "In active schedule"
                          : "Outside active schedule"}
                      </span>
                    </>
                  )}
                </span>
              </button>
            );
          })}
      </div>
      <p className="figure-footnote">
        Untested conditions carry no estimate. Selecting an observed condition
        changes inspection; it never starts another experiment.
      </p>
    </div>
  );
}

export function SelectedCondition({
  folio,
  observation,
  onInspect,
}: {
  folio: Folio;
  observation: Observation;
  onInspect: () => void;
}) {
  return (
    <section
      className="selected-condition"
      aria-label="Selected observed condition"
    >
      <div className="selected-condition-heading">
        <div>
          <span className="eyebrow">PINNED FOR INSPECTION</span>
          <h3>
            {observation.condition_label ??
              conditionLabel(folio, observation.condition_id)}
          </h3>
        </div>
        <ScopePill scope={observation.scope} />
      </div>
      <ResultStats folio={folio} observation={observation} />
      {observation.warning ? (
        <p className="scientific-warning">{textValue(observation.warning)}</p>
      ) : null}
      <div className="selected-condition-footer">
        <button className="text-button" onClick={onInspect}>
          Trace this computation <ArrowUpRight size={14} />
        </button>
        <ArtifactLink sha={observation.artifact_sha256}>
          Measurement artifact
        </ArtifactLink>
      </div>
      <SeedSpread observation={observation} />
    </section>
  );
}
