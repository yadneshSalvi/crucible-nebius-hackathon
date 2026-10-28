import { browserExecutable } from "../scripts/browser.mjs";
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";

const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const failures = [];
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
for (const width of [320, 390, 768, 1024, 1440, 1600]) {
  await page.setViewportSize({ width, height: 1000 });
  for (const stage of [
    "library",
    "contract",
    "reproduction",
    "challenge",
    "confirmation",
    "folio",
  ]) {
    await page.goto(
      `http://127.0.0.1:4201/${stage === "library" ? "" : `?folio=occupancy&stage=${stage}&inspect=computation`}`,
    );
    await page.locator("h1").waitFor();
    await page.evaluate(() => document.fonts.ready);
    const overflow = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      outliers: [...document.querySelectorAll("body *")]
        .filter((element) => {
          const rect = element.getBoundingClientRect();
          return (
            rect.width > 0 &&
            rect.right > innerWidth + 1 &&
            !element.closest(
              ".plot-scroll,.table-scroll,.stage-navigation,.dialog",
            )
          );
        })
        .slice(0, 8)
        .map((element) => `${element.tagName}.${element.className}`),
    }));
    if (overflow.scrollWidth > width + 1)
      failures.push({ width, stage, overflow });
    if (
      [320, 768, 1440, 1600].includes(width) &&
      ["library", "folio", "challenge"].includes(stage)
    )
      await page.screenshot({
        path: new URL(`${stage}-${width}.png`, output).pathname,
        fullPage: true,
      });
  }
}
const audits = [];
for (const width of [320, 1440, 1600]) {
  await page.setViewportSize({ width, height: 1000 });
  for (const stage of [
    "library",
    "contract",
    "challenge",
    "confirmation",
    "folio",
  ]) {
    await page.goto(
      `http://127.0.0.1:4201/${stage === "library" ? "" : `?folio=occupancy&stage=${stage}&inspect=computation`}`,
    );
    await page.locator("h1").waitFor();
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    if (result.violations.length)
      audits.push({
        width,
        stage,
        violations: result.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact,
          help: violation.help,
          nodes: violation.nodes.map((node) => ({
            target: node.target,
            summary: node.failureSummary,
          })),
        })),
      });
  }
}
await page.setViewportSize({ width: 390, height: 844 });
await page.goto("http://127.0.0.1:4201/?folio=occupancy&stage=folio");
await page.locator("h1").waitFor();
await page.getByRole("button", { name: "Evidence trail", exact: true }).click();
await page.getByRole("dialog").waitFor();
await page.getByRole("tab", { name: "Data", exact: true }).click();
await page.keyboard.press("ArrowRight");
const keyboardTab = await page.getByRole("tab", { selected: true }).innerText();
await page.keyboard.press("Escape");
const restoredFocus = await page
  .getByRole("button", { name: "Evidence trail", exact: true })
  .evaluate((element) => element === document.activeElement);
const result = {
  overflowFailures: failures,
  axeViolations: audits,
  pageErrors: errors,
  inspectorKeyboardTab: keyboardTab,
  inspectorFocusRestored: restoredFocus,
};
await writeFile(
  new URL("responsive-accessibility.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));
await browser.close();
if (
  failures.length ||
  audits.length ||
  errors.length ||
  keyboardTab !== "Compute" ||
  !restoredFocus
)
  process.exitCode = 1;
