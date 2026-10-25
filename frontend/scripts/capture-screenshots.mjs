import { randomBytes } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { access, appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { constants } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(scriptDirectory, "..", "..");
const frontendRoot = join(projectRoot, "frontend");
const screenshotsDirectory = join(projectRoot, "screenshots");
const credentialsPath = join(screenshotsDirectory, ".env.screenshots.local");
const databasePath = join(screenshotsDirectory, "screenshot-demo.sqlite3");
const databaseUrl = "sqlite:///./screenshots/screenshot-demo.sqlite3";
const python = join(projectRoot, "backend", ".venv", "Scripts", "python.exe");
const apiPort = Number(process.env.SCREENSHOT_API_PORT || 8010);
const webPort = Number(process.env.SCREENSHOT_WEB_PORT || 5173);
const apiUrl = `http://127.0.0.1:${apiPort}`;
const webUrl = `http://127.0.0.1:${webPort}`;

const credentialKeys = [
  "SCREENSHOT_REGULAR_USERNAME",
  "SCREENSHOT_REGULAR_PASSWORD",
  "SCREENSHOT_ADMIN_USERNAME",
  "SCREENSHOT_ADMIN_PASSWORD",
  "SCREENSHOT_JWT_SECRET",
];

function randomSecret(bytes = 24) {
  return randomBytes(bytes).toString("base64url");
}

function parseConfig(contents) {
  return Object.fromEntries(
    contents
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"))
      .map((line) => {
        const separator = line.indexOf("=");
        return separator < 0 ? ["", ""] : [line.slice(0, separator), line.slice(separator + 1)];
      })
      .filter(([key]) => key),
  );
}

async function loadCredentials() {
  await mkdir(screenshotsDirectory, { recursive: true });
  let config = {};
  try {
    config = parseConfig(await readFile(credentialsPath, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  const generated = {};
  const suffix = randomBytes(5).toString("hex");
  const defaults = {
    SCREENSHOT_REGULAR_USERNAME: `screenshot-user-${suffix}`,
    SCREENSHOT_REGULAR_PASSWORD: randomSecret(),
    SCREENSHOT_ADMIN_USERNAME: `screenshot-admin-${suffix}`,
    SCREENSHOT_ADMIN_PASSWORD: randomSecret(),
    SCREENSHOT_JWT_SECRET: randomSecret(48),
  };

  for (const key of credentialKeys) {
    if (!process.env[key] && !config[key]) generated[key] = defaults[key];
  }

  if (Object.keys(generated).length > 0) {
    const lines = Object.entries(generated).map(([key, value]) => `${key}=${value}`);
    await appendFile(credentialsPath, `${lines.join("\n")}\n`, { encoding: "utf8", mode: 0o600 });
  }

  const credentials = Object.fromEntries(
    credentialKeys.map((key) => [key, process.env[key] || config[key] || generated[key]]),
  );
  for (const [key, value] of Object.entries(credentials)) {
    if (!value || /[\r\n]/.test(value)) {
      throw new Error(`Invalid local screenshot configuration for ${key}.`);
    }
  }
  if (
    credentials.SCREENSHOT_REGULAR_USERNAME === credentials.SCREENSHOT_ADMIN_USERNAME ||
    credentials.SCREENSHOT_REGULAR_PASSWORD.length < 8 ||
    credentials.SCREENSHOT_ADMIN_PASSWORD.length < 8 ||
    Buffer.byteLength(credentials.SCREENSHOT_ADMIN_PASSWORD, "utf8") > 72
  ) {
    throw new Error("Screenshot account configuration is invalid; use distinct usernames and valid passwords.");
  }
  return credentials;
}

function start(command, args, options) {
  const child = spawn(command, args, {
    ...options,
    stdio: "ignore",
    windowsHide: true,
  });
  child.once("error", () => {});
  return child;
}

async function waitForServer(child, url, label) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${label} exited before becoming ready. Check that its port is available.`);
    }
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch {
      await new Promise((resolveWait) => setTimeout(resolveWait, 300));
    }
  }
  throw new Error(`${label} did not become ready at its local address.`);
}

async function apiRequest(path, options) {
  const response = await fetch(`${apiUrl}${path}`, options);
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  return { response, data };
}

async function ensureAccount(username, password, expectedRole, register) {
  if (register) {
    const { response } = await apiRequest("/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok && response.status !== 409) {
      throw new Error(`Local account registration failed with HTTP ${response.status}.`);
    }
  }

  const { response: loginResponse, data: login } = await apiRequest("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!loginResponse.ok || !login?.access_token) {
    throw new Error(`Local ${expectedRole} account login failed with HTTP ${loginResponse.status}.`);
  }

  const { response: profileResponse, data: profile } = await apiRequest("/auth/me", {
    headers: { Authorization: `Bearer ${login.access_token}` },
  });
  if (!profileResponse.ok || profile?.role !== expectedRole) {
    throw new Error(`Local account does not have the expected ${expectedRole} role.`);
  }
}

async function loginThroughUi(page, username, password) {
  await page.goto(webUrl, { waitUntil: "networkidle" });
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.locator("form").first().getByRole("button", { name: "Sign in", exact: true }).click();
  const userLabel = page.locator(".user-label");
  await userLabel.waitFor({ state: "visible", timeout: 10000 });
  if (!(await userLabel.innerText()).includes(username)) {
    throw new Error("The signed-in account label does not match the configured local account.");
  }
  await page.locator(".vehicle-card, .empty-state").first().waitFor({ state: "visible" });
}

async function stop(child) {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolveExit) => child.once("exit", resolveExit)),
    new Promise((resolveWait) => setTimeout(resolveWait, 5000)),
  ]);
}

async function main() {
  for (const port of [apiPort, webPort]) {
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      throw new Error("Screenshot server ports must be integers between 1024 and 65535.");
    }
  }
  await access(python, constants.X_OK).catch(() => {
    throw new Error("Backend virtual environment is missing; create backend\\.venv and install backend requirements first.");
  });
  const credentials = await loadCredentials();
  const environment = {
    ...process.env,
    DATABASE_URL: databaseUrl,
    JWT_SECRET_KEY: credentials.SCREENSHOT_JWT_SECRET,
    ADMIN_USERNAME: credentials.SCREENSHOT_ADMIN_USERNAME,
    ADMIN_PASSWORD: credentials.SCREENSHOT_ADMIN_PASSWORD,
    VITE_API_URL: apiUrl,
  };

  const seeded = spawnSync(python, ["-m", "backend.seed_data"], {
    cwd: projectRoot,
    env: environment,
    encoding: "utf8",
    windowsHide: true,
  });
  if (seeded.status !== 0) {
    throw new Error("Could not seed the isolated screenshot database.");
  }

  let backend;
  let frontend;
  let browser;
  try {
    backend = start(
      python,
      ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", String(apiPort)],
      { cwd: projectRoot, env: environment },
    );
    await waitForServer(backend, `${apiUrl}/health`, "Backend");
    await ensureAccount(
      credentials.SCREENSHOT_ADMIN_USERNAME,
      credentials.SCREENSHOT_ADMIN_PASSWORD,
      "admin",
      false,
    );
    await ensureAccount(
      credentials.SCREENSHOT_REGULAR_USERNAME,
      credentials.SCREENSHOT_REGULAR_PASSWORD,
      "user",
      true,
    );

    frontend = start(
      process.execPath,
      [join(frontendRoot, "node_modules", "vite", "bin", "vite.js"), "--host", "127.0.0.1", "--port", String(webPort), "--strictPort"],
      { cwd: frontendRoot, env: environment },
    );
    await waitForServer(frontend, webUrl, "Frontend");

    browser = await chromium.launch({ channel: "msedge", headless: true });
    const guestPage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await guestPage.goto(webUrl, { waitUntil: "networkidle" });
    await guestPage.locator(".vehicle-card").first().waitFor({ state: "visible", timeout: 10000 });
    await guestPage.screenshot({
      path: join(screenshotsDirectory, "inventory-public.png"),
      fullPage: true,
    });

    const regularPage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await loginThroughUi(
      regularPage,
      credentials.SCREENSHOT_REGULAR_USERNAME,
      credentials.SCREENSHOT_REGULAR_PASSWORD,
    );
    await regularPage.screenshot({
      path: join(screenshotsDirectory, "inventory-regular-user.png"),
      fullPage: true,
    });

    const adminPage = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    await loginThroughUi(
      adminPage,
      credentials.SCREENSHOT_ADMIN_USERNAME,
      credentials.SCREENSHOT_ADMIN_PASSWORD,
    );
    await adminPage.locator(".role-badge").getByText("Admin", { exact: true }).waitFor({ state: "visible" });
    await adminPage.screenshot({
      path: join(screenshotsDirectory, "inventory-admin.png"),
      fullPage: true,
    });
  } finally {
    if (browser) await browser.close();
    await stop(frontend);
    await stop(backend);
  }

  console.log("Saved local screenshots:");
  for (const file of ["inventory-public.png", "inventory-regular-user.png", "inventory-admin.png"]) {
    console.log(join(screenshotsDirectory, file));
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
