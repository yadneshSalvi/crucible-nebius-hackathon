import { browserExecutable } from "../scripts/browser.mjs";
import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";

const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 320, height: 844 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto(
  "http://127.0.0.1:4201/?folio=86e95abb99ee458f&stage=contract&inspect=source",
);
await expect(
  page.getByText("Proposed · unverified assumptions", { exact: true }),
).toBeVisible();
await expect(
  page.getByText(
    "Independence of adjacent Occupancy days is unestablished. A model-supplied assumption does not establish it.",
    { exact: true },
  ),
).toBeVisible();
const warningOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > innerWidth,
);
const warningAxe = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
await page.locator(".model-note .notice").screenshot({
  path: new URL("model-assumptions-warning-320.png", output).pathname,
});
await page.goto(
  "http://127.0.0.1:4201/?folio=8dde382738104c9a&stage=challenge&inspect=review",
);
await expect(
  page.getByText("Accepted change is applied to the active schedule.", {
    exact: true,
  }),
).toBeVisible();
const atlasCount = await page.locator(".atlas-intro .mono").innerText();
await page.locator(".atlas-row-observed").last().click();
const selectedCondition = new URL(page.url()).searchParams.get("condition");
await expect(page.locator(".atlas-row-selected")).toHaveCount(1);
const acceptedEvidenceAxe = await new AxeBuilder({ page })
  .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
  .analyze();
await page.screenshot({
  path: new URL("accepted-evidence-320.png", output).pathname,
  fullPage: true,
});
await page.getByRole("button", { name: "Evidence trail", exact: true }).click();
await page.getByRole("tab", { name: "Data", exact: true }).click();
await page.reload();
await page.locator("h1").waitFor();
await expect(page.getByRole("dialog")).toHaveCount(0);
const drawerClosedOnReload = (await page.getByRole("dialog").count()) === 0;
const tabRetained = new URL(page.url()).searchParams.get("inspect") === "data";
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto(
  "http://127.0.0.1:4201/?folio=86e95abb99ee458f&stage=challenge",
);
await page.locator("h1").waitFor();
let registrationDialogVerified = false;
const registerButton = page.getByRole("button", {
  name: "Register selected condition",
  exact: true,
});
if (await registerButton.count()) {
  await registerButton.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page
      .getByRole("dialog")
      .getByText(/You will launch confirmation separately/),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  registrationDialogVerified = true;
}
await page.goto("http://127.0.0.1:4201/?folio=occupancy&stage=folio");
await page.locator("h1").waitFor();
const initialArtifactRows = await page
  .locator(".artifact-list-row:visible")
  .count();
await page.locator(".artifact-record > summary").click();
const expandedArtifactRows = await page
  .locator(".artifact-list-row:visible")
  .count();
await page.screenshot({
  path: new URL("folio-1280-artifact-manifest.png", output).pathname,
  fullPage: false,
});
const result = {
  pageErrors: errors,
  warningOverflow,
  warningViolations: warningAxe.violations.map((violation) => violation.id),
  acceptedEvidenceViolations: acceptedEvidenceAxe.violations.map(
    (violation) => violation.id,
  ),
  atlasCount,
  selectedCondition,
  drawerClosedOnReload,
  tabRetained,
  registrationDialogVerified,
  initialArtifactRows,
  expandedArtifactRows,
};
await writeFile(
  new URL("final-ui-checks.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));
await browser.close();
if (
  errors.length ||
  warningOverflow ||
  warningAxe.violations.length ||
  acceptedEvidenceAxe.violations.length ||
  !drawerClosedOnReload ||
  !tabRetained ||
  initialArtifactRows ||
  !expandedArtifactRows
)
  process.exitCode = 1;
