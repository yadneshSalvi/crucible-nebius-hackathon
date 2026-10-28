import { useId, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleAlert,
  Clock3,
  Eye,
  Fingerprint,
  FlaskConical,
  Image as ImageIcon,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Maximize2,
  Pause,
  Play,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Sprout,
} from "lucide-react";
import { Button, ExternalSource, Hash, Mark, Pill } from "./ui";
import type { WheatCell, WheatStudy } from "./wheat-types";
import "./wheat.css";

export interface WheatProps {
  study: WheatStudy | null;
  loading: boolean;
  error: string | null;
  pending: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  onHistory: () => void;
  onRefresh: () => void;
}

const human = (value: string) => value.replaceAll("_", " ");
const numeric = (value: number | null | undefined, digits = 1) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US", { maximumFractionDigits: digits })
    : "—";
const bytes = (value: number | null | undefined) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value < 1024) return `${numeric(value, 0)} B`;
  if (value < 1024 ** 2) return `${numeric(value / 1024)} KB`;
  return `${numeric(value / 1024 ** 2)} MB`;
};
const duration = (value: number | null | undefined) =>
  typeof value === "number" && Number.isFinite(value)
    ? value < 1000
      ? `${numeric(value, 0)} ms`
      : `${numeric(value / 1000, 2)} s`
    : "—";
const valueText = (value: unknown) =>
  value === null || value === undefined
    ? "Unspecified"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const hasAction = (study: WheatStudy, action: string) =>
  study.capabilities.includes(action);
const measured = (cell: WheatCell | undefined) =>
  cell?.status === "succeeded" && cell.metrics !== null;
function recipeFamily(study: WheatStudy, id?: string) {
  const declared = study.recipes.find((item) => item.id === id)?.family;
  if (declared) return declared;
  if (id?.includes("tiles")) return "tiles";
  if (id?.includes("multiscale")) return "multiscale";
  if (id?.includes("noop")) return "noop";
  return "full";
}

export function Wheat({
  study,
  loading,
  error,
  pending,
  onAction,
  onHistory,
  onRefresh,
}: WheatProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<"original" | "transformed">("original");
  const [layers, setLayers] = useState({
    matched: true,
    missed: true,
    duplicate: true,
    false_positive: false,
    targets: true,
  });
  const [selectedBox, setSelectedBox] = useState<string | null>(null);
  const [boxTable, setBoxTable] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const imageId = useId();
  const selected =
    study?.cells.find((cell) => cell.id === selectedId) ??
    study?.cells.find((cell) => measured(cell)) ??
    study?.cells[0];
  const asset = study?.asset;
  const isMeasured = measured(selected);
  const recipe = study?.recipes.find((item) => item.id === selected?.recipe_id);
  const widths = [
    ...new Set(study?.cells.map((cell) => cell.retained_width) ?? []),
  ].sort((a, b) => b - a);
  const missed = new Set(selected?.missed_target_ids ?? []);
  const sourceImage =
    view === "transformed" && selected?.transform
      ? selected.transform.url
      : asset?.url;
  const running =
    pending ||
    Boolean(
      study?.run &&
      ["running", "queued", "cancel_requested"].includes(study.run.status),
    );
  const completed = study?.cells.filter((cell) => measured(cell)).length ?? 0;
  const can = (action: string) =>
    Boolean(study && hasAction(study, action) && !running);
  const choose = (cell: WheatCell) => {
    setSelectedId(cell.id);
    setSelectedBox(null);
  };

  return (
    <main className="wheat-page" id="main-content" tabIndex={-1}>
      <div className="wheat-topline">
        <div className="wheat-breadcrumb">
          <span className="wheat-index">FIELD NOTES / 01</span>
          <span className="wheat-breadcrumb-rule" />
          <span>Wheat-head counting</span>
        </div>
        <button className="text-button" onClick={onHistory}>
          Previous experiments <ArrowUpRight size={14} />
        </button>
      </div>

      <header className="wheat-introduction">
        <div className="wheat-introduction-copy">
          <p className="eyebrow">
            <Sprout size={14} /> THE IMAGE IS THE EXPERIMENT
          </p>
          <h1>
            How many pixels
            <br />
            does a count need<span>?</span>
          </h1>
          <p className="wheat-deck">
            Keep the field. Change the image. Follow every head the detector
            finds — and every one it misses.
          </p>
        </div>
        <aside className="wheat-question">
          <span className="eyebrow">THE DECISION</span>
          <p>
            Can this pipeline send a smaller image and still make an acceptable
            count?
          </p>
          <div className="wheat-question-note">
            <FlaskConical size={15} /> Authored benchmark requirements
          </div>
          <span className="fine-print">
            External practitioner threshold and independent review are not
            established.
          </span>
        </aside>
      </header>

      {error ? (
        <div className="wheat-error" role="alert">
          <CircleAlert size={19} />
          <p>{error}</p>
          <button className="text-button" onClick={onRefresh}>
            Refresh evidence <ArrowRight size={14} />
          </button>
        </div>
      ) : null}

      {!study ? (
        <section className="wheat-opening" aria-busy={loading}>
          <Mark />
          <div>
            <span className="eyebrow">EVIDENCE WORKSPACE</span>
            <h2>
              {loading
                ? "Opening the field notebook"
                : "The study is not available"}
            </h2>
            <p>
              {loading
                ? "Reading the source, experiment and custody records."
                : "Refresh to retrieve the saved experiment."}
            </p>
          </div>
          {loading ? (
            <LoaderCircle size={22} className="spin" />
          ) : (
            <Button onClick={onRefresh}>Refresh</Button>
          )}
        </section>
      ) : (
        <>
          <div className="wheat-contextbar">
            <div>
              <span className="wheat-context-dot" />{" "}
              {human(study.experiment_kind)}
            </div>
            <span>
              {completed} / {study.cells.length} recorded conditions
            </span>
            {study.run?.status === "succeeded" && !running ? (
              <span className="wheat-context-last-operation">
                {human(study.run.action)} · succeeded
              </span>
            ) : null}
            <span className="mono">
              REV {String(study.revision).padStart(2, "0")}
            </span>
          </div>

          {study.status === "assets_pending" ||
          study.source_readiness?.missing_images ||
          (asset && hasAction(study, "prepare")) ? (
            <div className="wheat-source-readiness" role="status">
              <ImageIcon size={18} />
              <div>
                <span className="eyebrow">
                  {study.source_readiness?.missing_images === 0
                    ? "SOURCE CORPUS / AUDIT REQUIRED"
                    : "SOURCE CORPUS / INCOMPLETE"}
                </span>
                <strong>
                  {study.source_readiness
                    ? `${numeric(study.source_readiness.available_images, 0)} / ${numeric(study.source_readiness.required_images, 0)} declared source images available`
                    : "Released illustration available. Study preparation is incomplete."}
                </strong>
                <p>
                  {study.source_readiness?.detail ??
                    "The declared source corpus must be available and audited before detector training. Source annotations on the illustration are not inference results."}
                </p>
              </div>
              {hasAction(study, "prepare") ? (
                <Button
                  icon={<ImageIcon size={14} />}
                  disabled={!can("prepare")}
                  onClick={() => onAction("prepare")}
                >
                  Prepare declared corpus
                </Button>
              ) : null}
              {hasAction(study, "compile_sources") ? (
                <Button
                  icon={<Sparkles size={14} />}
                  disabled={!can("compile_sources")}
                  onClick={() => onAction("compile_sources")}
                >
                  Compile source protocol
                </Button>
              ) : null}
            </div>
          ) : null}

          {study.run ? (
            <div
              className={`wheat-run ${study.run.error ? "wheat-run-error" : ""} ${!running && !study.run.error && study.run.status === "succeeded" ? "wheat-run-complete" : ""}`}
              role="status"
              aria-live="polite"
            >
              {running ? (
                <LoaderCircle size={17} className="spin" />
              ) : study.run.error ? (
                <CircleAlert size={17} />
              ) : (
                <Clock3 size={17} />
              )}
              <div>
                <strong>
                  {human(study.run.action)} · {human(study.run.status)}
                </strong>
                <p>{study.run.error ?? study.run.checkpoint}</p>
              </div>
              {running && hasAction(study, "cancel") ? (
                <Button
                  tone="quiet"
                  icon={<Pause size={14} />}
                  onClick={() => onAction("cancel")}
                  disabled={pending}
                >
                  Cancel
                </Button>
              ) : null}
              {!running &&
              study.run.can_resume &&
              hasAction(study, "resume") ? (
                <Button
                  icon={<Play size={14} />}
                  onClick={() => onAction("resume")}
                >
                  Resume
                </Button>
              ) : null}
            </div>
          ) : null}

          {asset &&
          !study.training.checkpoint_sha256 &&
          hasAction(study, "train") ? (
            <div className="wheat-setup-banner">
              <FlaskConical size={17} />
              <div>
                <strong>Source image prepared. The detector comes next.</strong>
                <p>
                  {study.training.detail ??
                    "Train the declared model before measuring the image conditions."}
                </p>
              </div>
              <Button
                icon={<Play size={14} />}
                disabled={!can("train")}
                onClick={() => onAction("train")}
              >
                Train detector
              </Button>
            </div>
          ) : null}

          <section className="wheat-workbench" aria-label="Image experiment">
            <div className="wheat-visual-column">
              <div className="wheat-image-toolbar">
                <div className="wheat-image-heading">
                  <span className="eyebrow">01 / OBSERVE</span>
                  <h2>The same field. Different information.</h2>
                </div>
                <div className="wheat-view-switch" aria-label="Image view">
                  <button
                    aria-pressed={view === "original"}
                    onClick={() => setView("original")}
                  >
                    Original
                  </button>
                  <button
                    aria-pressed={view === "transformed"}
                    disabled={!selected?.transform}
                    title={
                      !selected?.transform
                        ? "Run this condition to inspect its exact processed image."
                        : undefined
                    }
                    onClick={() => setView("transformed")}
                  >
                    Processed
                  </button>
                </div>
              </div>

              {asset ? (
                <figure
                  className="wheat-figure"
                  aria-describedby={`${imageId}-caption`}
                >
                  <div
                    className="wheat-image-stage"
                    style={{ aspectRatio: `${asset.width} / ${asset.height}` }}
                  >
                    <img
                      src={sourceImage}
                      alt={`Released GWHD wheat field photograph ${asset.id}, acquisition session ${asset.session_id}.`}
                      onError={() => setImageError(sourceImage ?? null)}
                      onLoad={() => setImageError(null)}
                    />
                    {imageError === sourceImage ? (
                      <div className="wheat-image-failure">
                        <CircleAlert size={24} />
                        <strong>Photograph could not be loaded</strong>
                        <p>
                          Refresh the evidence to restore this source asset.
                        </p>
                      </div>
                    ) : null}
                    {(isMeasured || asset.ground_truth_released) &&
                    selected &&
                    imageError !== sourceImage ? (
                      <svg
                        className="wheat-overlays"
                        viewBox={`0 0 ${asset.width} ${asset.height}`}
                        aria-hidden="true"
                      >
                        {asset.ground_truth_released && layers.targets
                          ? asset.targets.map((target) => (
                              <rect
                                key={`target-${target.id}`}
                                className={`wheat-box wheat-box-target ${selectedBox === `target:${target.id}` ? "wheat-box-selected" : ""}`}
                                x={target.bbox[0]}
                                y={target.bbox[1]}
                                width={target.bbox[2]}
                                height={target.bbox[3]}
                              />
                            ))
                          : null}
                        {isMeasured &&
                        asset.ground_truth_released &&
                        layers.missed
                          ? asset.targets
                              .filter((target) => missed.has(target.id))
                              .map((target) => (
                                <rect
                                  key={`miss-${target.id}`}
                                  onClick={() => {
                                    setSelectedBox(`target:${target.id}`);
                                    setBoxTable(true);
                                  }}
                                  className={`wheat-box wheat-box-missed ${selectedBox === `target:${target.id}` ? "wheat-box-selected" : ""}`}
                                  x={target.bbox[0]}
                                  y={target.bbox[1]}
                                  width={target.bbox[2]}
                                  height={target.bbox[3]}
                                />
                              ))
                          : null}
                        {(isMeasured ? selected.predictions : [])
                          .filter((prediction) => layers[prediction.match_kind])
                          .map((prediction) => (
                            <rect
                              key={prediction.id}
                              onClick={() => {
                                setSelectedBox(`prediction:${prediction.id}`);
                                setBoxTable(true);
                              }}
                              className={`wheat-box wheat-box-${prediction.match_kind} ${selectedBox === `prediction:${prediction.id}` ? "wheat-box-selected" : ""}`}
                              x={prediction.bbox[0]}
                              y={prediction.bbox[1]}
                              width={prediction.bbox[2]}
                              height={prediction.bbox[3]}
                            />
                          ))}
                      </svg>
                    ) : null}
                    <div className="wheat-image-tag">
                      <span />
                      {view === "transformed" && selected?.transform
                        ? `${selected.transform.width} × ${selected.transform.height} processed pixels`
                        : `${asset.width} × ${asset.height} original pixels`}
                    </div>
                    <div className="wheat-image-corner">
                      <Maximize2 size={14} />
                      <span>ORIGINAL COORDINATES</span>
                    </div>
                    {!isMeasured && !selectedBox ? (
                      <div className="wheat-image-unrun">
                        <ScanLine size={19} />
                        <div>
                          <strong>
                            {selected?.status === "running"
                              ? "Detector is running"
                              : "This condition has no recorded predictions"}
                          </strong>
                          <span>
                            {selected?.error ??
                              "The original photograph is shown. Run the condition to inspect its measured result."}
                          </span>
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <figcaption
                    id={`${imageId}-caption`}
                    className="wheat-image-caption"
                  >
                    <span>
                      <strong title={asset.id}>
                        {asset.id.length > 20
                          ? `${asset.id.slice(0, 12)}…`
                          : asset.id}
                      </strong>
                      <span className="wheat-caption-separator">/</span>Session{" "}
                      {asset.session_id}
                      <span className="wheat-caption-separator">/</span>
                      {human(asset.split)}
                    </span>
                    <ExternalSource url={asset.source_url}>
                      {asset.license} · GWHD
                    </ExternalSource>
                  </figcaption>
                  <div
                    className="wheat-legend"
                    aria-label="Detection overlay layers"
                  >
                    {(
                      [
                        ["matched", "Matched", "wheat-dot-matched"],
                        ["missed", "Missed", "wheat-dot-missed"],
                        ["duplicate", "Duplicate", "wheat-dot-duplicate"],
                        [
                          "false_positive",
                          "Other false positives",
                          "wheat-dot-false",
                        ],
                        ["targets", "Source annotations", "wheat-dot-target"],
                      ] as const
                    ).map(([key, label, color]) => (
                      <label
                        key={key}
                        className={
                          !isMeasured && key !== "targets"
                            ? "wheat-layer-disabled"
                            : ""
                        }
                      >
                        <input
                          type="checkbox"
                          checked={layers[key]}
                          disabled={
                            (key !== "targets" && !isMeasured) ||
                            ((key === "missed" || key === "targets") &&
                              !asset.ground_truth_released)
                          }
                          onChange={(event) =>
                            setLayers((current) => ({
                              ...current,
                              [key]: event.target.checked,
                            }))
                          }
                        />
                        <span className={`wheat-legend-dot ${color}`} />
                        {label}
                      </label>
                    ))}
                    <button
                      className="wheat-box-table-toggle"
                      onClick={() => setBoxTable(!boxTable)}
                      disabled={!isMeasured && !asset.ground_truth_released}
                      aria-expanded={boxTable}
                    >
                      <Eye size={14} /> Box records <ChevronDown size={13} />
                    </button>
                  </div>
                  {asset.ground_truth_released && !isMeasured ? (
                    <p className="wheat-annotation-status">
                      {asset.targets.length} released source annotations · no
                      detector predictions or measured errors
                    </p>
                  ) : null}
                </figure>
              ) : (
                <div className="wheat-asset-gate">
                  <div className="wheat-asset-gate-visual">
                    <Sprout size={58} strokeWidth={1} />
                    <span className="wheat-gate-coordinate">
                      GWHD / SOURCE QUALIFICATION
                    </span>
                  </div>
                  <div className="wheat-asset-gate-copy">
                    <span className="eyebrow">
                      A REAL PHOTOGRAPH STARTS HERE
                    </span>
                    <h3>Bring the field into focus.</h3>
                    <p>
                      Prepare the licensed source image and its acquisition
                      record before opening the experiment.
                    </p>
                    <Button
                      tone="primary"
                      icon={<ImageIcon size={16} />}
                      disabled={!can("prepare")}
                      busy={pending}
                      onClick={() => onAction("prepare")}
                    >
                      Prepare source assets
                    </Button>
                    {!can("prepare") && !running ? (
                      <p className="fine-print">
                        Source preparation is unavailable. Check the source and
                        hardware evidence below.
                      </p>
                    ) : null}
                  </div>
                </div>
              )}

              {boxTable &&
              selected &&
              asset &&
              (isMeasured || asset.ground_truth_released) ? (
                <div className="wheat-box-records">
                  <div>
                    <h3>Every box has a record.</h3>
                    <p>
                      Coordinates are [x, y, width, height] in the original
                      image. Select a record to highlight it.
                    </p>
                  </div>
                  <div className="wheat-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Box</th>
                          <th>Outcome</th>
                          <th>Original coordinates</th>
                          <th>Score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {asset.ground_truth_released
                          ? asset.targets.map((target) => (
                              <tr
                                key={`miss-${target.id}`}
                                className={
                                  selectedBox === `target:${target.id}`
                                    ? "is-selected"
                                    : ""
                                }
                              >
                                <td>
                                  <button
                                    aria-pressed={
                                      selectedBox === `target:${target.id}`
                                    }
                                    onClick={() =>
                                      setSelectedBox(`target:${target.id}`)
                                    }
                                  >
                                    {target.id}
                                  </button>
                                </td>
                                <td>
                                  <span
                                    className={
                                      isMeasured && missed.has(target.id)
                                        ? "wheat-text-missed"
                                        : ""
                                    }
                                  >
                                    {isMeasured && missed.has(target.id)
                                      ? "Missed target"
                                      : "Annotated target"}
                                  </span>
                                </td>
                                <td className="mono">
                                  {target.bbox
                                    .map((n) => numeric(n))
                                    .join(", ")}
                                </td>
                                <td>—</td>
                              </tr>
                            ))
                          : null}
                        {(isMeasured ? selected.predictions : []).map(
                          (prediction) => (
                            <tr
                              key={prediction.id}
                              className={
                                selectedBox === `prediction:${prediction.id}`
                                  ? "is-selected"
                                  : ""
                              }
                            >
                              <td>
                                <button
                                  aria-pressed={
                                    selectedBox ===
                                    `prediction:${prediction.id}`
                                  }
                                  onClick={() =>
                                    setSelectedBox(
                                      `prediction:${prediction.id}`,
                                    )
                                  }
                                >
                                  {prediction.id}
                                </button>
                              </td>
                              <td>{human(prediction.match_kind)}</td>
                              <td className="mono">
                                {prediction.bbox
                                  .map((n) => numeric(n))
                                  .join(", ")}
                              </td>
                              <td className="mono">
                                {numeric(prediction.score, 3)}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                  {isMeasured ? (
                    <p className="fine-print">
                      Matching threshold: IoU{" "}
                      {numeric(selected.iou_threshold, 2)} · detector score ≥{" "}
                      {numeric(selected.score_threshold, 2)}. Duplicate boxes
                      are additional predictions on an already matched target.
                    </p>
                  ) : (
                    <p className="fine-print">
                      These boxes are released source annotations. Detector
                      predictions, matching outcomes and localization
                      measurements have not been computed.
                    </p>
                  )}
                </div>
              ) : null}

              <div className="wheat-visual-footnote">
                <Fingerprint size={14} />
                <p>
                  {asset
                    ? (asset.selection_rule ??
                      "One released discovery illustration; aggregate evidence is reported separately below.")
                    : "No substitute image or generated field is used. The source photograph appears after qualification."}
                </p>
              </div>
            </div>

            <aside
              className="wheat-controls"
              aria-label="Image intervention and measured result"
            >
              <div className="wheat-control-section">
                <span className="eyebrow">02 / INTERVENE</span>
                <h2>
                  Pixels retained
                  <br />
                  before upload
                </h2>
                <p className="wheat-control-description">
                  One discrete image transform.
                  <br />
                  The photograph and detector stay fixed.
                </p>
                <div
                  className="wheat-widths"
                  aria-label="Pixels retained before upload"
                >
                  {widths.map((width) => {
                    const cell = study.cells.find(
                      (item) =>
                        item.retained_width === width &&
                        recipeFamily(study, item.recipe_id) ===
                          recipeFamily(study, selected?.recipe_id),
                    );
                    return (
                      <button
                        key={width}
                        aria-label={`${width} px`}
                        aria-pressed={selected?.retained_width === width}
                        disabled={!cell}
                        title={
                          !cell
                            ? "This width is not declared for the selected inference recipe."
                            : undefined
                        }
                        onClick={() => cell && choose(cell)}
                      >
                        <strong>{width}</strong>
                        <span>px</span>
                        <i
                          className={measured(cell) ? "is-measured" : ""}
                          aria-label={
                            measured(cell) ? "recorded result" : "not recorded"
                          }
                        />
                      </button>
                    );
                  })}
                </div>
                <p className="wheat-control-qualification">
                  Digital resampling · not a change in camera, flight altitude
                  or crop biology.
                </p>
                <label
                  className="wheat-recipe-label"
                  htmlFor={`${imageId}-recipe`}
                >
                  <Layers3 size={14} /> Inference recipe
                </label>
                <select
                  id={`${imageId}-recipe`}
                  value={selected?.recipe_id ?? ""}
                  onChange={(event) => {
                    const cell =
                      study.cells.find(
                        (item) =>
                          item.recipe_id === event.target.value &&
                          item.retained_width === selected?.retained_width,
                      ) ??
                      study.cells.find(
                        (item) => item.recipe_id === event.target.value,
                      );
                    if (cell) choose(cell);
                  }}
                >
                  {study.recipes.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
                {recipe?.description ? (
                  <p className="wheat-recipe-description">
                    {recipe.description}
                  </p>
                ) : null}
              </div>

              <div className="wheat-result-section" aria-live="polite">
                <div className="wheat-result-heading">
                  <span className="eyebrow">03 / MEASURE</span>
                  <span
                    className={`wheat-result-mode ${isMeasured ? "is-recorded" : ""}`}
                  >
                    {isMeasured
                      ? "RECORDED INFERENCE"
                      : selected
                        ? human(selected.status).toUpperCase()
                        : "NOT RUN"}
                  </span>
                </div>
                <div className="wheat-count-equation">
                  <div>
                    <strong>
                      {isMeasured
                        ? numeric(selected?.metrics?.predicted_count, 0)
                        : "—"}
                    </strong>
                    <span>detected</span>
                  </div>
                  <span className="wheat-equation-divider">/</span>
                  <div>
                    <strong>
                      {asset?.ground_truth_released
                        ? numeric(asset.targets.length, 0)
                        : "—"}
                    </strong>
                    <span>annotated heads</span>
                  </div>
                </div>
                {isMeasured && selected?.seed !== undefined ? (
                  <p className="wheat-illustration-seed">
                    Illustration seed {selected.seed} · one fixed training
                    repeat
                  </p>
                ) : null}
                <div className="wheat-result-grid">
                  <Metric
                    label="Absolute count error"
                    value={
                      isMeasured
                        ? numeric(selected?.metrics?.absolute_count_error, 0)
                        : "—"
                    }
                    unit="heads"
                  />
                  <Metric
                    label={
                      selected?.metrics?.localization_metric ?? "Localization"
                    }
                    value={
                      isMeasured
                        ? numeric(selected?.metrics?.localization_value, 3)
                        : "—"
                    }
                  />
                  <Metric
                    label="Uploaded image"
                    value={isMeasured ? bytes(selected?.metrics?.bytes) : "—"}
                  />
                  <Metric
                    label="Inference time"
                    value={
                      isMeasured ? duration(selected?.metrics?.wall_ms) : "—"
                    }
                  />
                </div>
                {isMeasured ? (
                  <p className="wheat-single-image-note">
                    This photograph only. Whole-corpus results follow below.
                  </p>
                ) : (
                  <p className="wheat-single-image-note">
                    Measurements appear after this condition completes.
                  </p>
                )}
                <Button
                  tone="primary"
                  className="wheat-run-button"
                  icon={isMeasured ? <Check size={16} /> : <Play size={15} />}
                  busy={selected?.status === "running"}
                  disabled={
                    !selected ||
                    !selected.enabled ||
                    !can("run_cell") ||
                    isMeasured
                  }
                  onClick={() =>
                    selected && onAction("run_cell", { cell_id: selected.id })
                  }
                >
                  {isMeasured ? "Evidence recorded" : "Run this condition"}
                </Button>
                {!isMeasured &&
                (!selected?.enabled || !hasAction(study, "run_cell")) ? (
                  <p className="wheat-prerequisite">
                    {selected?.disabled_reason ??
                      "Prepare the source and train the detector before running a condition."}
                  </p>
                ) : null}
                {selected?.error ? (
                  <p className="wheat-prerequisite wheat-text-missed">
                    {selected.error}
                  </p>
                ) : null}
              </div>
              <div className="wheat-controlled-note">
                <LockKeyhole size={14} />
                <p>
                  Fixed weights, threshold and matching rule. Boxes map back to
                  original image coordinates.
                </p>
              </div>
            </aside>
          </section>

          <section className="wheat-lower-grid">
            <div className="wheat-comparisons">
              <div className="wheat-section-heading">
                <div>
                  <span className="eyebrow">THE MEASURED TRADE-OFF</span>
                  <h2>Keep the whole denominator.</h2>
                </div>
                <span className="wheat-section-index">04</span>
              </div>
              <p className="wheat-section-deck">
                Every declared condition, including the ones that have not run.
                Session counts describe this corpus; no independence or
                confidence interval is implied.
              </p>
              <div className="wheat-table-scroll">
                <table className="wheat-comparison-table">
                  <thead>
                    <tr>
                      <th>Configuration</th>
                      <th>
                        Count MAE<small>heads / image</small>
                      </th>
                      <th>Localization</th>
                      <th>
                        Upload<small>total bytes</small>
                      </th>
                      <th>
                        Runtime<small>total</small>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {study.cells.map((cell) => (
                      <tr
                        key={cell.id}
                        className={
                          cell.id === selected?.id ? "is-selected" : ""
                        }
                      >
                        <td>
                          <button
                            onClick={() => choose(cell)}
                            aria-pressed={cell.id === selected?.id}
                          >
                            <span
                              className={`wheat-table-state ${measured(cell) ? "is-measured" : cell.status === "failed" ? "is-failed" : ""}`}
                            />
                            <span>
                              <strong>{cell.label}</strong>
                              <small>
                                {cell.aggregate
                                  ? `${cell.aggregate.n_images} images · ${cell.aggregate.n_sessions} sessions`
                                  : human(cell.status)}
                              </small>
                              {cell.aggregate?.seeds?.length ? (
                                <small>
                                  {cell.aggregate.seeds.length} fixed seeds (
                                  {cell.aggregate.seeds.join(", ")}); averaged
                                  within image
                                </small>
                              ) : null}
                            </span>
                            {cell.id === study.registration.cell_id ? (
                              <LockKeyhole
                                size={12}
                                aria-label="Registered configuration"
                              />
                            ) : null}
                          </button>
                        </td>
                        <td>
                          {cell.aggregate
                            ? numeric(cell.aggregate.count_mae, 2)
                            : "—"}
                        </td>
                        <td>
                          {cell.aggregate
                            ? numeric(cell.aggregate.localization_value, 3)
                            : "—"}
                        </td>
                        <td>
                          {cell.aggregate
                            ? bytes(cell.aggregate.total_upload_bytes)
                            : "—"}
                        </td>
                        <td>
                          {cell.aggregate
                            ? duration(cell.aggregate.total_wall_ms)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="wheat-attribution">
                <Layers3 size={15} />
                <span>
                  <ExternalSource url="https://github.com/obss/sahi">
                    SAHI is established prior work
                  </ExternalSource>
                  , not a Crucible invention. Tiling cannot restore pixels
                  discarded before upload. Resource comparisons use measured
                  costs.
                </span>
              </p>
            </div>
            <Planning
              study={study}
              can={can}
              pending={pending}
              onAction={onAction}
            />
          </section>

          <section
            className="wheat-decision"
            aria-label="Registered benchmark decision"
          >
            <div className="wheat-decision-symbol">
              <ShieldCheck size={29} strokeWidth={1.3} />
            </div>
            <div className="wheat-decision-copy">
              <span className="eyebrow">WHAT THE EVIDENCE PERMITS</span>
              <h2>{study.decision.label}</h2>
              <p>{study.decision.reason}</p>
              {study.decision.limitations.length ? (
                <ul>
                  {study.decision.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </div>
            <div className="wheat-decision-actions">
              <Button
                icon={<LockKeyhole size={15} />}
                disabled={!selected || !measured(selected) || !can("register")}
                onClick={() =>
                  selected && onAction("register", { cell_id: selected.id })
                }
              >
                {study.registration.sha256
                  ? "Registration frozen"
                  : "Register selected policy"}
              </Button>
              <Button
                tone="primary"
                icon={<ArrowRight size={16} />}
                disabled={!can("evaluate")}
                busy={pending && study.run?.action === "evaluate"}
                onClick={() => onAction("evaluate")}
              >
                Open registered evaluation
              </Button>
              <p>
                Authored benchmark requirement. A deployed policy and
                practitioner impact are not established.
              </p>
            </div>
          </section>

          <section
            className="wheat-evidence-section"
            aria-label="Source and immutable evidence"
          >
            <div className="wheat-section-heading">
              <div>
                <span className="eyebrow">FOLLOW THE EVIDENCE</span>
                <h2>Open the notebook.</h2>
              </div>
              <span className="wheat-section-index">05</span>
            </div>
            <div className="wheat-evidence-grid">
              <details
                className="wheat-evidence-card"
                open={study.source_fields.some(
                  (field) => field.status === "unresolved",
                )}
              >
                <summary>
                  <span className="wheat-evidence-icon">
                    <Fingerprint size={19} />
                  </span>
                  <span>
                    <strong>Source → protocol</strong>
                    <small>
                      {
                        study.source_fields.filter(
                          (field) => field.status === "unresolved",
                        ).length
                      }{" "}
                      unresolved fields · {study.source_fields.length} traced
                      fields
                    </small>
                  </span>
                  <ChevronDown size={17} />
                </summary>
                <div className="wheat-evidence-body">
                  <p className="wheat-evidence-intro">
                    Version ambiguity is a source-resolution task. No
                    configuration is selected because it produces a better
                    number.
                  </p>
                  {study.source_fields.map((field) => (
                    <div className="wheat-source-field" key={field.key}>
                      <div className="wheat-source-field-title">
                        <strong>{field.label}</strong>
                        <Pill
                          tone={
                            field.status === "unresolved"
                              ? "ochre"
                              : field.status === "source_supported"
                                ? "teal"
                                : "neutral"
                          }
                        >
                          {human(field.status)}
                        </Pill>
                      </div>
                      {field.candidates.map((candidate, index) => (
                        <div
                          className="wheat-source-candidate"
                          key={`${field.key}-${index}`}
                        >
                          <code>{valueText(candidate.value)}</code>
                          <ExternalSource url={candidate.url}>
                            {candidate.source_title}
                            {candidate.locator ? ` · ${candidate.locator}` : ""}
                          </ExternalSource>
                        </div>
                      ))}
                      {field.selected_value !== undefined ? (
                        <p>
                          <strong>Executed value:</strong>{" "}
                          {valueText(field.selected_value)}
                        </p>
                      ) : null}
                      {field.reason ? <p>{field.reason}</p> : null}
                    </div>
                  ))}
                  <Button
                    tone="quiet"
                    icon={<Sparkles size={14} />}
                    disabled={!can("compile_sources")}
                    onClick={() => onAction("compile_sources")}
                  >
                    Compile source fields with Nemotron
                  </Button>
                  {study.source_compilation ? (
                    <div className="wheat-source-compilation">
                      <div className="wheat-source-field-title">
                        <span className="eyebrow">
                          NEMOTRON / SOURCE COMPILATION
                        </span>
                        <Pill tone="neutral">
                          {human(study.source_compilation.status)}
                        </Pill>
                      </div>
                      <p className="wheat-evidence-intro">
                        {study.source_compilation.method_label ??
                          "Advisory source structuring with exact references."}{" "}
                        Scientific verification requires the registered
                        computation and verifier.
                      </p>
                      {study.source_compilation.fields.map((field, index) => (
                        <div
                          className="wheat-compiled-field"
                          key={`${field.field}-${index}`}
                        >
                          <strong>{field.field}</strong>
                          <code>{field.value}</code>
                          <ExternalSource url={field.url ?? field.source_id}>
                            {field.source_id} · {field.locator}
                          </ExternalSource>
                          <span>{human(field.status)}</span>
                        </div>
                      ))}
                      <h4>Recorded conflict resolution</h4>
                      <p>{study.source_compilation.conflict_resolution}</p>
                      {study.source_compilation.unresolved?.length ? (
                        <ul>
                          {study.source_compilation.unresolved.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      ) : null}
                      {study.source_compilation.limitation ? (
                        <p>{study.source_compilation.limitation}</p>
                      ) : null}
                      <p className="fine-print">
                        Receipt:{" "}
                        {study.source_compilation.receipt_id ?? "Not recorded"}
                      </p>
                    </div>
                  ) : null}
                  <Button
                    tone="quiet"
                    icon={<ArrowUpRight size={14} />}
                    disabled={!can("retrieve")}
                    onClick={() => onAction("retrieve")}
                  >
                    Retrieve primary-source evidence
                  </Button>
                  {study.evidence_change ? (
                    <div className="wheat-evidence-change">
                      <span className="eyebrow">
                        RETRIEVAL → RECIPE CHANGE ·{" "}
                        {human(study.evidence_change.status)}
                      </span>
                      <h4>{study.evidence_change.assumption}</h4>
                      <p>{study.evidence_change.explanation}</p>
                      <p>
                        <strong>Before:</strong>{" "}
                        {study.evidence_change.before.join(", ") || "None"}
                      </p>
                      <p>
                        <strong>After:</strong>{" "}
                        {study.evidence_change.after.join(", ") || "None"}
                      </p>
                      {study.evidence_change.source ? (
                        <ExternalSource url={study.evidence_change.source.url}>
                          {study.evidence_change.source.title}
                        </ExternalSource>
                      ) : null}
                      <div className="wheat-evidence-change-actions">
                        <Button
                          disabled={!can("accept_evidence")}
                          onClick={() => onAction("accept_evidence")}
                        >
                          Accept change
                        </Button>
                        <Button
                          tone="quiet"
                          disabled={!can("reject_evidence")}
                          onClick={() => onAction("reject_evidence")}
                        >
                          Decline
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </details>

              <details className="wheat-evidence-card">
                <summary>
                  <span className="wheat-evidence-icon">
                    <FlaskConical size={19} />
                  </span>
                  <span>
                    <strong>Detector & computation</strong>
                    <small>
                      {study.training.detector} · {human(study.training.status)}
                    </small>
                  </span>
                  <ChevronDown size={17} />
                </summary>
                <div className="wheat-evidence-body">
                  <dl className="wheat-evidence-facts">
                    <div>
                      <dt>Training state</dt>
                      <dd>{human(study.training.status)}</dd>
                    </div>
                    <div>
                      <dt>Device</dt>
                      <dd>{study.training.device}</dd>
                    </div>
                    <div>
                      <dt>Declared epochs</dt>
                      <dd>{numeric(study.training.epochs, 0)}</dd>
                    </div>
                    <div>
                      <dt>Training receipt</dt>
                      <dd>{study.training.receipt_id ?? "Not recorded"}</dd>
                    </div>
                  </dl>
                  {study.training.detail ? (
                    <p>{study.training.detail}</p>
                  ) : null}
                  <Hash
                    value={study.training.checkpoint_sha256 ?? undefined}
                    label={
                      study.training.checkpoint_set_sha256
                        ? "CHECKPOINT SET"
                        : "CHECKPOINT"
                    }
                  />
                  <Button
                    icon={<Play size={14} />}
                    disabled={!can("train")}
                    onClick={() => onAction("train")}
                  >
                    Train declared detector
                  </Button>
                  <p className="fine-print">
                    The trusted detector computes boxes and measurements. NVIDIA
                    Nemotron proposes experiments from released evidence.
                  </p>
                  {selected?.transform ? (
                    <div className="wheat-transform-record">
                      <span className="eyebrow">SELECTED TRANSFORM</span>
                      <p>
                        {selected.transform.resampler} ·{" "}
                        {selected.transform.encoding} ·{" "}
                        {selected.transform.width} × {selected.transform.height}
                      </p>
                      <p>{selected.transform.coordinate_mapping}</p>
                      <Hash value={selected.transform.sha256} label="PIXELS" />
                    </div>
                  ) : null}
                </div>
              </details>

              <details className="wheat-evidence-card">
                <summary>
                  <span className="wheat-evidence-icon">
                    <LockKeyhole size={19} />
                  </span>
                  <span>
                    <strong>Registration & custody</strong>
                    <small>
                      {human(study.registration.status)} ·{" "}
                      {human(study.custody.exposure_status)}
                    </small>
                  </span>
                  <ChevronDown size={17} />
                </summary>
                <div className="wheat-evidence-body">
                  <div className="wheat-custody-item">
                    <span className="wheat-custody-node" />
                    <span className="eyebrow">IMMUTABLE REGISTRATION</span>
                    <h4>{human(study.registration.status)}</h4>
                    <p>
                      {study.registration.detail ??
                        "The selected policy, controls and authored requirements must be frozen before final evaluation."}
                    </p>
                    <dl className="wheat-evidence-facts">
                      <div>
                        <dt>Registered configuration</dt>
                        <dd>
                          {study.registration.cell_id ?? "Not registered"}
                        </dd>
                      </div>
                      <div>
                        <dt>Registered at</dt>
                        <dd>
                          {study.registration.registered_at ?? "Not registered"}
                        </dd>
                      </div>
                      <div>
                        <dt>Review status</dt>
                        <dd>{human(study.registration.review_status)}</dd>
                      </div>
                    </dl>
                    <Hash
                      value={study.registration.sha256 ?? undefined}
                      label="REGISTRATION"
                    />
                    {study.registration.requirement ? (
                      <pre className="wheat-json">
                        {JSON.stringify(
                          study.registration.requirement,
                          null,
                          2,
                        )}
                      </pre>
                    ) : null}
                  </div>
                  <div className="wheat-custody-item">
                    <span className="wheat-custody-node" />
                    <span className="eyebrow">DATA CUSTODY</span>
                    <h4>{human(study.custody.status)}</h4>
                    <p>{study.custody.detail}</p>
                    <dl className="wheat-evidence-facts">
                      <div>
                        <dt>Exposure</dt>
                        <dd>{human(study.custody.exposure_status)}</dd>
                      </div>
                      <div>
                        <dt>External custodian</dt>
                        <dd>
                          {study.custody.external_custodian ??
                            "None established"}
                        </dd>
                      </div>
                    </dl>
                    <Hash
                      value={study.custody.dataset_fingerprint ?? undefined}
                      label="DATASET"
                    />
                    <Hash
                      value={study.custody.split_manifest_sha256 ?? undefined}
                      label="SPLIT MANIFEST"
                    />
                    <p className="wheat-custody-caveat">
                      {study.custody.public_benchmark_caveat}
                    </p>
                  </div>
                </div>
              </details>

              <details className="wheat-evidence-card">
                <summary>
                  <span className="wheat-evidence-icon">
                    <ArrowDownToLine size={19} />
                  </span>
                  <span>
                    <strong>Receipts & rerunnable evidence</strong>
                    <small>
                      {study.receipts.length} service receipts ·{" "}
                      {study.artifacts.length} artifacts
                    </small>
                  </span>
                  <ChevronDown size={17} />
                </summary>
                <div className="wheat-evidence-body">
                  {study.receipts.length ? (
                    study.receipts.map((receipt) => (
                      <div className="wheat-receipt" key={receipt.id}>
                        <div>
                          <strong>
                            {receipt.provider ?? receipt.kind ?? "Computation"}
                            {receipt.model ? ` · ${receipt.model}` : ""}
                          </strong>
                          <Pill
                            tone={
                              receipt.status === "succeeded" ||
                              receipt.status === "complete"
                                ? "teal"
                                : receipt.status === "failed"
                                  ? "error"
                                  : "neutral"
                            }
                          >
                            {human(receipt.status)}
                          </Pill>
                        </div>
                        <p>{receipt.purpose}</p>
                        <code>{receipt.id}</code>
                        <span className="fine-print">
                          {duration(receipt.elapsed_ms)}
                          {receipt.request_id
                            ? ` · request ${receipt.request_id}`
                            : ""}
                        </span>
                        {receipt.error ? (
                          <p className="wheat-text-missed">{receipt.error}</p>
                        ) : null}
                        {receipt.url ? (
                          <a className="text-link" href={receipt.url}>
                            Inspect receipt <ArrowUpRight size={13} />
                          </a>
                        ) : null}
                      </div>
                    ))
                  ) : (
                    <p>No service or compute receipts have been recorded.</p>
                  )}
                  {study.artifacts.map((artifact, index) => (
                    <a
                      className="wheat-artifact"
                      href={artifact.url}
                      key={artifact.id ?? `${artifact.url}-${index}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ArrowDownToLine size={16} />
                      <span>
                        {artifact.label ??
                          artifact.name ??
                          artifact.kind ??
                          "Evidence artifact"}
                        {artifact.sha256 ? (
                          <code>{artifact.sha256.slice(0, 14)}…</code>
                        ) : null}
                      </span>
                      <ArrowUpRight size={14} />
                    </a>
                  ))}
                  {study.export_url ? (
                    <a
                      className="button button-primary"
                      href={study.export_url}
                    >
                      <ArrowDownToLine size={16} />
                      Download rerunnable folio
                    </a>
                  ) : hasAction(study, "build_export") ? (
                    <Button
                      icon={<ArrowDownToLine size={16} />}
                      disabled={!can("build_export")}
                      onClick={() => onAction("build_export")}
                    >
                      Build rerunnable folio
                    </Button>
                  ) : (
                    <p className="fine-print">
                      The evidence export becomes available after registered
                      verification.
                    </p>
                  )}
                </div>
              </details>
            </div>
          </section>

          <footer className="wheat-footer">
            <div>
              <span className="eyebrow">BOUNDED BY THE EVIDENCE.</span>
              <p>
                {study.scope ??
                  "A source-informed wheat benchmark workbench. Head counting does not establish yield or deployment impact."}
              </p>
              {study.limitations.length ? (
                <details>
                  <summary>
                    Scope & limitations ({study.limitations.length})
                  </summary>
                  <ul>
                    {study.limitations.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
              {asset ? (
                <p className="wheat-photo-credit">
                  Photograph: {asset.attribution} · {asset.license}
                </p>
              ) : null}
            </div>
            <button className="text-button" onClick={onHistory}>
              Occupancy & XOR history <ArrowUpRight size={14} />
            </button>
          </footer>
        </>
      )}
    </main>
  );
}

function Metric({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="wheat-metric">
      <span>{label}</span>
      <strong>
        {value}
        {unit ? <small> {unit}</small> : null}
      </strong>
    </div>
  );
}

function Planning({
  study,
  can,
  pending,
  onAction,
}: {
  study: WheatStudy;
  can: (action: string) => boolean;
  pending: boolean;
  onAction: WheatProps["onAction"];
}) {
  const next = study.cells.find(
    (cell) => cell.id === study.planning.next_cell_id,
  );
  return (
    <aside className="wheat-planning">
      <div className="wheat-planning-top">
        <span className="wheat-planning-icon">
          <Sparkles size={20} strokeWidth={1.5} />
        </span>
        <span className="eyebrow">NVIDIA NEMOTRON / NEXT EXPERIMENT</span>
      </div>
      <h2>
        Ask a better
        <br />
        next question.
      </h2>
      <p>
        {study.planning.proposal ??
          "Distinguish lost image detail from an inference-scale problem. The planner selects from conditions that have not run."}
      </p>
      {next ? (
        <div className="wheat-next-cell">
          <span className="eyebrow">PROPOSED CONDITION</span>
          <strong>{next.label}</strong>
          <span>{study.planning.rationale}</span>
        </div>
      ) : null}
      {study.planning.competing_predictions?.length ? (
        <div className="wheat-competing">
          <span className="eyebrow">PREDICTIONS RECORDED BEFORE RUN</span>
          {study.planning.competing_predictions.map((item) => (
            <div key={item.explanation}>
              <strong>{item.explanation}</strong>
              <p>{item.prediction}</p>
            </div>
          ))}
        </div>
      ) : null}
      {study.planning.observed_result ? (
        <div className="wheat-observed-result">
          <span className="eyebrow">OBSERVED AFTER EXECUTION</span>
          <p>{study.planning.observed_result}</p>
        </div>
      ) : null}
      <div className="wheat-planning-actions">
        <Button
          tone="primary"
          icon={<Sparkles size={15} />}
          disabled={!can("plan_next")}
          busy={pending && study.run?.action === "plan_next"}
          onClick={() => onAction("plan_next")}
        >
          {study.planning.receipt_id
            ? "Revisit next experiment"
            : "Propose next experiment"}
        </Button>
        {next ? (
          <Button
            icon={<Play size={14} />}
            disabled={!can("execute_plan")}
            onClick={() => onAction("execute_plan")}
          >
            Run proposed condition
          </Button>
        ) : null}
      </div>
      <p className="wheat-planning-boundary">
        {study.planning.receipt_id
          ? `Recorded model receipt: ${study.planning.receipt_id}`
          : "No model-selected experiment is recorded yet."}{" "}
        The planner receives released discovery evidence; final labels stay
        outside its context.
      </p>
    </aside>
  );
}
