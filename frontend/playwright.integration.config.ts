import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "**/*.integration.spec.ts",
  workers: 1,
  timeout: 120000,
  use: {
    baseURL: "http://127.0.0.1:3011",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    channel:
      process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined),
    viewport: { width: 1440, height: 1000 },
  },
  webServer: [
    {
      command:
        process.platform === "win32"
          ? '"..\\.venv\\Scripts\\python.exe" "..\\backend\\tests\\e2e_server.py"'
          : "../.venv/bin/python ../backend/tests/e2e_server.py",
      url: "http://127.0.0.1:8011/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 180000,
    },
    {
      command: "npm run dev -- --port 3011",
      url: "http://127.0.0.1:3011",
      env: { BACKEND_URL: "http://127.0.0.1:8011" },
      reuseExistingServer: !process.env.CI,
      timeout: 180000,
    },
  ],
});
