import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8099";
const postgresURL =
  process.env.E2E_POSTGRES_URL ??
  "postgres://postgres:postgres@127.0.0.1:55432/resume_e2e";
const resumeServiceHost =
  process.env.RESUME_SERVICE_HOST ?? "http://127.0.0.1:3001";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    navigationTimeout: 60_000,
    actionTimeout: 15_000,
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium",
      testMatch: /.*\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: ".auth/admin.json",
      },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command:
      "cd ../application_manager && " +
      "E2E_STUBS=1 TINYFISH_API_KEY=e2e " +
      `E2E_POSTGRES_URL='${postgresURL}' ` +
      `RESUME_SERVICE_HOST='${resumeServiceHost}' ` +
      "poetry run python -m application_manager.e2e_server",
    url: `${baseURL}/admin/login/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
