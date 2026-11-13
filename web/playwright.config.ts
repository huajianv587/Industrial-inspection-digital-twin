import { defineConfig } from '@playwright/test'

const desktopViewports = [
  { name: 'desktop-1024x768', width: 1024, height: 768 },
  { name: 'desktop-1280x720', width: 1280, height: 720 },
  { name: 'desktop-1440x900', width: 1440, height: 900 },
]

export default defineConfig({
  testDir: './e2e',
  // Exclude macOS/ExFAT AppleDouble metadata files from the test collector.
  testIgnore: /(^|[/\\])\._/,
  // The digital-twin pages exercise WebGL and animated camera feeds. Keep
  // local Chrome validation deterministic instead of competing for the GPU.
  fullyParallel: false,
  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  timeout: 20_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: 'http://127.0.0.1:5178',
    browserName: 'chromium',
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: desktopViewports.map((viewport) => ({
    name: viewport.name,
    use: { viewport: { width: viewport.width, height: viewport.height } },
  })),
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5178 --strictPort',
    url: 'http://127.0.0.1:5178',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    env: {
      ...process.env,
      VITE_SUPABASE_URL: 'http://127.0.0.1:54321',
      VITE_SUPABASE_ANON_KEY: 'playwright-local-only',
      VITE_API_BASE_URL: '/api/v1',
    },
  },
})
