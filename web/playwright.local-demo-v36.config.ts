import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e-local-demo',
  testMatch: 'v36-precision-industrial-realism.spec.ts',
  testIgnore: /(^|[/\\])\._/,
  fullyParallel: false,
  forbidOnly: true,
  reporter: 'list',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.LOCAL_DEMO_URL || 'http://127.0.0.1:5184',
    browserName: 'chromium',
    channel: 'chrome',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
