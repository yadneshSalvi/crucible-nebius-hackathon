import { existsSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "@playwright/test";

export async function browserExecutable() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (configured && existsSync(configured)) return configured;
  if (existsSync(chromium.executablePath())) return undefined;
  const cache =
    process.platform === "darwin"
      ? join(homedir(), "Library/Caches/ms-playwright")
      : process.platform === "win32"
        ? join(
            process.env.LOCALAPPDATA || join(homedir(), "AppData/Local"),
            "ms-playwright",
          )
        : join(homedir(), ".cache/ms-playwright");
  const installations = (await readdir(cache).catch(() => []))
    .filter((name) => /^chromium_headless_shell-\d+$/.test(name))
    .sort((a, b) => Number(b.split("-").at(-1)) - Number(a.split("-").at(-1)));
  for (const installation of installations) {
    for (const suffix of [
      "chrome-headless-shell-mac-arm64/chrome-headless-shell",
      "chrome-headless-shell-mac-x64/chrome-headless-shell",
      "chrome-linux/headless_shell",
      "chrome-headless-shell-linux64/chrome-headless-shell",
      "chrome-win/headless_shell.exe",
    ]) {
      const path = join(cache, installation, suffix);
      if (existsSync(path)) return path;
    }
  }
  throw new Error(
    "Chromium is not installed. Run npx playwright install chromium, or set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH to an existing browser.",
  );
}
