import { browserExecutable } from "../scripts/browser.mjs";
import { chromium, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

const browser = await chromium.launch({
  executablePath: await browserExecutable(),
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const output = new URL("./qa-output/", import.meta.url);
await mkdir(output, { recursive: true });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:4201/");
await page
  .getByRole("button", { name: "Start a research folio", exact: true })
  .click();
await expect(page.getByRole("dialog")).toBeVisible();
await page.getByRole("radio", { name: /Controlled synthetic case/ }).check();
await page.locator("#new-title").fill("UI QA — reviewed synthetic workflow");
await page
  .getByRole("button", { name: "Create research folio", exact: true })
  .click();
await expect(page).toHaveURL(/folio=/);
const id = new URL(page.url()).searchParams.get("folio");
const read = async () =>
  (await page.request.get(`http://127.0.0.1:4201/api/folios/${id}`)).json();
await expect
  .poll(async () => Boolean((await read()).source), { timeout: 45000 })
  .toBe(true);
await expect(page.locator("#claim")).toBeEnabled({ timeout: 15000 });
const originalClaim = await page.locator("#claim").inputValue();
await page
  .locator("#claim")
  .fill(
    `${originalClaim} This is an automated UI workflow check of the fixed adapter.`,
  );
await page.getByRole("button", { name: "Save revision", exact: true }).click();
await expect(page.getByText("Saved revision 2", { exact: true })).toBeVisible();
await page
  .getByRole("button", { name: "Review & lock contract", exact: true })
  .click();
await expect(page.getByRole("dialog")).toBeVisible();
await page.locator("#reviewer-name").fill("Automated UI QA (agent)");
await page
  .locator("#review-note")
  .fill(
    "Scripted local UI workflow acceptance. This is an agent QA record, not a human participant review or external scientific approval.",
  );
await page.getByRole("button", { name: "Keep reviewing", exact: true }).click();
const reviewFocusRestored = await page
  .getByRole("button", { name: "Review & lock contract", exact: true })
  .evaluate((element) => document.activeElement === element);
await page
  .getByRole("button", { name: "Review & lock contract", exact: true })
  .click();
await page.locator("#reviewer-name").fill("Automated UI QA (agent)");
await page
  .locator("#review-note")
  .fill(
    "Scripted local UI workflow acceptance. This is an agent QA record, not a human participant review or external scientific approval.",
  );
await page
  .getByRole("button", { name: "Record review & lock contract", exact: true })
  .click();
await expect(page).toHaveURL(/stage=reproduction/);
await page
  .getByRole("button", { name: "Run original comparison", exact: true })
  .click();
await page
  .getByRole("button", { name: "Cancel operation", exact: true })
  .click();
await expect
  .poll(async () => (await read()).status, { timeout: 30000 })
  .toBe("cancelled");
await expect(
  page.getByRole("button", { name: "Resume saved attempt", exact: true }),
).toBeVisible({ timeout: 15000 });
await page.screenshot({
  path: new URL("cancelled-operation-1280.png", output).pathname,
  fullPage: true,
});
await page
  .getByRole("button", { name: "Resume saved attempt", exact: true })
  .click();
await expect
  .poll(async () => (await read()).status, { timeout: 60000 })
  .toBe("baseline_review");
await expect(
  page.getByRole("button", {
    name: "Review & accept reproduction",
    exact: true,
  }),
).toBeVisible({ timeout: 15000 });
await page
  .getByRole("button", { name: "Review & accept reproduction", exact: true })
  .click();
await page.locator("#reviewer-name").fill("Automated UI QA (agent)");
await page
  .getByRole("button", { name: "Accept reproduction review", exact: true })
  .click();
await expect(page).toHaveURL(/stage=challenge/);
await expect(
  page.getByRole("button", { name: "Retrieve source evidence", exact: true }),
).toBeEnabled();
const saved = await read();
const result = {
  folio: id,
  contractRevision: saved.contract.revision,
  contractLocked: saved.contract.locked,
  claimEdited: saved.claim !== originalClaim,
  reviewFocusRestored,
  status: saved.status,
  reproductionAccepted: saved.reproduction_accepted,
  numericalObservations: saved.observations.length,
  runAttempt: saved.run.attempt,
  role: saved.contract.approval.role,
  reviewName: saved.contract.approval.reviewer_name,
  pageErrors: errors,
};
await writeFile(
  new URL("ui-journey.json", output),
  JSON.stringify(result, null, 2),
);
console.log(JSON.stringify(result));
await browser.close();
if (errors.length || !reviewFocusRestored || !saved.reproduction_accepted)
  process.exitCode = 1;
