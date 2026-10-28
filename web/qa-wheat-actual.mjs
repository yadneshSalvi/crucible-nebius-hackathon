/** Read-only integration QA against public released wheat evidence. */
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { browserExecutable } from "../scripts/browser.mjs";

const base = process.env.CRUCIBLE_WHEAT_QA_URL ?? "http://127.0.0.1:4203";
const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const failures = [];
const errors = [];
const mutationRequests = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.route("**/api/**", async (route) => {
  if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method())) {
    mutationRequests.push({
      method: route.request().method(),
      url: route.request().url(),
    });
    await route.abort();
  } else await route.continue();
});
await page.goto(base);
await page.locator(".wheat-image-stage img").waitFor();
await page
  .locator(".wheat-image-stage img")
  .evaluate((image) => image.decode());
await page.evaluate(() => document.fonts.ready);
const study = await (await page.request.get(`${base}/api/wheat`)).json();
if (!study.asset?.ground_truth_released)
  failures.push("Source annotations were not released.");
if (study.cells.some((cell) => cell.metrics || cell.predictions.length))
  failures.push("This QA expects the actual unrun source-only study.");
if (
  study.capabilities.includes("compile_sources") &&
  !(await page
    .getByRole("button", {
      name: "Compile source fields with Nemotron",
      exact: true,
    })
    .isEnabled())
)
  failures.push("Source compiler unavailable before full source preparation.");
for (const name of [
  "Run this condition",
  "Register selected policy",
  "Open registered evaluation",
  "Train declared detector",
]) {
  if (
    !(await page
      .getByRole("button", { name, exact: true, includeHidden: true })
      .isDisabled())
  )
    failures.push(`Action ${name} enabled before source preparation.`);
}
if (
  await page
    .locator(
      ".wheat-box-missed,.wheat-box-matched,.wheat-box-duplicate,.wheat-box-false_positive",
    )
    .count()
)
  failures.push("Unrun photograph displayed prediction outcomes.");
const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const geometry = [];
const accessibilityFailures = [];
for (const width of [320, 390, 768, 1024, 1440, 1920]) {
  await page.setViewportSize({ width, height: 1100 });
  const result = await page.evaluate((targets) => {
    const image = document.querySelector(".wheat-image-stage img");
    const svg = document.querySelector(".wheat-overlays");
    const stage = image.getBoundingClientRect();
    const scale = Math.min(
      stage.width / image.naturalWidth,
      stage.height / image.naturalHeight,
    );
    const offsetX = stage.x + (stage.width - image.naturalWidth * scale) / 2;
    const offsetY = stage.y + (stage.height - image.naturalHeight * scale) / 2;
    const ctm = svg.getScreenCTM();
    const targetRects = [...document.querySelectorAll(".wheat-box-target")];
    return {
      viewport: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      targetCount: targetRects.length,
      allBoxesMatchSource: targetRects.every((rect, index) =>
        ["x", "y", "width", "height"].every(
          (key, coordinate) =>
            Number(rect.getAttribute(key)) === targets[index].bbox[coordinate],
        ),
      ),
      scaleDifference: Math.max(
        Math.abs(ctm.a - scale),
        Math.abs(ctm.d - scale),
      ),
      xDifference: Math.abs(ctm.e - offsetX),
      yDifference: Math.abs(ctm.f - offsetY),
    };
  }, study.asset.targets);
  geometry.push(result);
  if (
    result.scrollWidth > width + 1 ||
    result.targetCount !== study.asset.targets.length ||
    !result.allBoxesMatchSource ||
    result.scaleDifference > 0.001 ||
    result.xDifference > 0.1 ||
    result.yDifference > 0.1
  )
    failures.push({ width, geometry: result });
  const audit = await new AxeBuilder({ page })
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
      path: new URL(`wheat-actual-${width}.png`, output).pathname,
      fullPage: true,
    });
}
await page.setViewportSize({ width: 1440, height: 1100 });
await page.locator(".wheat-figure").screenshot({
  path: new URL("wheat-actual-source-boxes.png", output).pathname,
});
const entryViewports = [];
for (const viewport of [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
]) {
  await page.setViewportSize(viewport);
  await page.evaluate(() => scrollTo(0, 0));
  const entry = await page.evaluate(() => {
    const image = document
      .querySelector(".wheat-image-stage")
      .getBoundingClientRect();
    const measurement = document
      .querySelector(".wheat-result-heading")
      .getBoundingClientRect();
    const readiness = document
      .querySelector(".wheat-source-readiness")
      .getBoundingClientRect();
    return {
      width: innerWidth,
      height: innerHeight,
      imageTop: image.top,
      visibleImageHeight:
        Math.min(image.bottom, innerHeight) - Math.max(image.top, 0),
      measurementHeadingVisible:
        measurement.top >= 0 && measurement.bottom <= innerHeight,
      readinessVisible: readiness.top >= 0 && readiness.bottom <= innerHeight,
    };
  });
  entryViewports.push(entry);
  if (
    entry.visibleImageHeight < (viewport.height === 720 ? 250 : 400) ||
    !entry.measurementHeadingVisible ||
    !entry.readinessVisible
  )
    failures.push({ entryViewport: entry });
  await page.screenshot({
    path: new URL(
      `wheat-entry-${viewport.width}x${viewport.height}.png`,
      output,
    ).pathname,
  });
}
await page
  .getByRole("checkbox", { name: "Source annotations", exact: true })
  .uncheck();
if (await page.locator(".wheat-box-target").count())
  failures.push("Source annotation toggle did not hide boxes.");
await page
  .getByRole("checkbox", { name: "Source annotations", exact: true })
  .check();
await page.getByRole("button", { name: "Box records", exact: true }).click();
if (
  (await page
    .getByRole("cell", { name: "Annotated target", exact: true })
    .count()) !== study.asset.targets.length
)
  failures.push("Source box records were not distinctly annotated.");
const targetButton = page.getByRole("button", {
  name: "target-0",
  exact: true,
});
const selectionBefore = await targetButton.getAttribute("aria-pressed");
await targetButton.focus();
await page.keyboard.press("Enter");
const selectionAfter = await targetButton.getAttribute("aria-pressed");
const selectionFeedback = {
  before: selectionBefore,
  after: selectionAfter,
  activatedWith: "Enter",
  obstructingBanner: await page.locator(".wheat-image-unrun").count(),
};
if (
  selectionBefore !== "false" ||
  selectionAfter !== "true" ||
  selectionFeedback.obstructingBanner
)
  failures.push({ selectionFeedback });
if ((await page.locator(".wheat-box-target.wheat-box-selected").count()) !== 1)
  failures.push(
    "Keyboard-accessible box selection did not highlight the annotation.",
  );
await page.getByRole("button", { name: "512 px", exact: true }).click();
if (
  (await page.locator(".wheat-box-target").count()) !==
  study.asset.targets.length
)
  failures.push("Source boxes disappeared on unrun condition selection.");
await page
  .getByRole("button", { name: "Previous experiments", exact: true })
  .click();
await page.waitForURL(/view=history/);
if (await page.locator(".wheat-page").count())
  failures.push("History route still displays the wheat workspace.");
await page.goBack();
await page.locator(".wheat-image-stage img").waitFor();
if (new URL(page.url()).searchParams.has("view"))
  failures.push("Back navigation did not restore the default wheat route.");
if (mutationRequests.length)
  failures.push("A mutation request occurred during read-only QA.");
const result = {
  study_id: study.id,
  revision: study.revision,
  status: study.status,
  capabilities: study.capabilities,
  released_target_count: study.asset.targets.length,
  geometry,
  entryViewports,
  selectionFeedback,
  failures,
  accessibilityFailures,
  pageErrors: errors,
  mutationRequests,
};
await writeFile(
  new URL("wheat-actual-qa.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (
  failures.length ||
  accessibilityFailures.length ||
  errors.length ||
  mutationRequests.length
)
  process.exitCode = 1;
