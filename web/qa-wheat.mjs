/** Isolated, explicitly unrun UI fixture. Never produces scientific evidence. */
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { browserExecutable } from "../scripts/browser.mjs";

const fixture = {
  schema_version: "wheat-ui-qa-unrun-fixture",
  id: "ui-qa-unrun-fixture",
  revision: 0,
  title: "Unrun layout fixture",
  experiment_kind: "new_source_informed_experiment",
  status: "draft",
  scope: "Explicitly unrun UI fixture. No scientific result.",
  limitations: [
    "External methodological review and practitioner acceptance requirement are pending.",
  ],
  capabilities: ["prepare"],
  asset: null,
  cells: [1024, 768, 512, 256].map((width) => ({
    id: `full-${width}`,
    label: `${width}px · full image`,
    recipe_id: "full",
    retained_width: width,
    status: "unrun",
    enabled: false,
    disabled_reason: "Prepare the source and train the detector first.",
    transform: null,
    predictions: [],
    missed_target_ids: [],
    metrics: null,
    aggregate: null,
  })),
  recipes: [
    {
      id: "full",
      label: "Full-image inference",
      description:
        "Fixed detector processing after the declared upload transform.",
    },
  ],
  source_fields: [
    {
      key: "epochs",
      label: "Training epochs",
      status: "unresolved",
      critical: true,
      candidates: [
        {
          value: 10,
          source_title: "Published supplement",
          url: "https://proceedings.mlr.press/v139/koh21a/koh21a-supp.pdf",
        },
        {
          value: 12,
          source_title: "Current repository defaults",
          url: "https://github.com/p-lambda/wilds",
        },
      ],
      reason: "Exact executable-paper correspondence remains unresolved.",
    },
  ],
  training: {
    status: "not_started",
    detector: "Declared detector",
    device: "Not qualified",
    detail: "UI fixture: no training has occurred.",
  },
  run: null,
  evidence_change: null,
  registration: {
    status: "not_registered",
    review_status: "external_review_pending",
  },
  custody: {
    status: "not_qualified",
    exposure_status: "unopened",
    public_benchmark_caveat:
      "Public availability cannot establish historical ignorance of the benchmark.",
  },
  planning: { status: "not_started" },
  decision: {
    status: "not_established",
    label: "The evidence is not complete yet.",
    reason:
      "Prepare source assets, train the declared detector, and run the registered experiment.",
    limitations: [
      "Authored demo requirements are not practitioner acceptance criteria.",
    ],
  },
  receipts: [],
  artifacts: [],
};

const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:4203/");
const entry = await (
  await page.request.get("http://127.0.0.1:4203/src/main.tsx")
).text();
const reactUrl = entry.match(/from "([^"]*\/react\.js\?[^"]+)"/)[1];
const domUrl = entry.match(/from "([^"]*\/react-dom_client\.js\?[^"]+)"/)[1];
await page.evaluate(
  async ({ study, reactUrl, domUrl }) => {
    const reactModule = await import(reactUrl);
    const domModule = await import(domUrl);
    const React = reactModule.default ?? reactModule;
    const ReactDOM = domModule.default ?? domModule;
    const { Wheat } = await import("/src/Wheat.tsx");
    const existing = document.querySelector("#root");
    if (existing) existing.style.display = "none";
    const container = document.createElement("div");
    container.id = "wheat-ui-qa-root";
    document.body.appendChild(container);
    window.__wheatQaActions = [];
    ReactDOM.createRoot(container).render(
      React.createElement(Wheat, {
        study,
        loading: false,
        error: null,
        pending: false,
        onAction: (action, payload) =>
          window.__wheatQaActions.push({ action, payload }),
        onHistory: () => window.__wheatQaActions.push({ action: "history" }),
        onRefresh: () => window.__wheatQaActions.push({ action: "refresh" }),
      }),
    );
  },
  { study: fixture, reactUrl, domUrl },
);
await page
  .getByRole("heading", { name: "How many pixels does a count need?" })
  .waitFor();
await page.evaluate(() => document.fonts.ready);
const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const overflowFailures = [];
const accessibilityFailures = [];
for (const width of [320, 390, 768, 1024, 1440]) {
  await page.setViewportSize({ width, height: 1000 });
  const overflow = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  if (overflow.document > width + 1) overflowFailures.push(overflow);
  const audit = await new AxeBuilder({ page })
    .include("#wheat-ui-qa-root")
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  if (audit.violations.length)
    accessibilityFailures.push({
      width,
      violations: audit.violations.map(({ id, nodes }) => ({
        id,
        nodes: nodes.map(({ target, failureSummary }) => ({
          target,
          failureSummary,
        })),
      })),
    });
  if ([390, 1440].includes(width))
    await page.screenshot({
      path: new URL(`wheat-unrun-${width}.png`, output).pathname,
      fullPage: true,
    });
}
await page.locator("#wheat-ui-qa-root details").evaluateAll((items) =>
  items.forEach((item) => {
    item.open = true;
  }),
);
const expandedAudit = await new AxeBuilder({ page })
  .include("#wheat-ui-qa-root")
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
if (expandedAudit.violations.length)
  accessibilityFailures.push({
    width: 1440,
    expanded: true,
    violations: expandedAudit.violations.map(({ id, nodes }) => ({
      id,
      nodes: nodes.map(({ target, failureSummary }) => ({
        target,
        failureSummary,
      })),
    })),
  });
await page.getByRole("button", { name: "512 px" }).click();
if (
  (await page
    .getByRole("button", { name: "512 px" })
    .getAttribute("aria-pressed")) !== "true"
)
  errors.push("Width selection did not persist.");
if (
  !(await page.getByRole("button", { name: "Run this condition" }).isDisabled())
)
  errors.push("Unprepared condition was executable.");
if (
  !(await page
    .getByRole("button", { name: "Register selected policy" })
    .isDisabled())
)
  errors.push("Unrun condition was registrable.");
await page.getByRole("button", { name: "Prepare source assets" }).click();
await page.getByRole("button", { name: "Previous experiments" }).click();
const actions = await page.evaluate(() => window.__wheatQaActions);
if (actions.map(({ action }) => action).join(",") !== "prepare,history")
  errors.push("Leaf action dispatch did not match the contract.");
const result = {
  fixture: fixture.id,
  overflowFailures,
  accessibilityFailures,
  pageErrors: errors,
  actions,
};
await writeFile(
  new URL("wheat-ui-qa.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (overflowFailures.length || accessibilityFailures.length || errors.length)
  process.exitCode = 1;
