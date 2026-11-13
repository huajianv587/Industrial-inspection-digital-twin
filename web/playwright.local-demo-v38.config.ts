import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e-local-demo',
  testMatch: ['v38-smooth-stream.spec.ts', 'v38-portal.spec.ts', 'v38-full-product.spec.ts', 'v39-ui-shell.spec.ts'],
  outputDir: './test-results-v38',
  testIgnore: /(^|[/\\])\._/,
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  reporter: 'list',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.LOCAL_DEMO_URL || 'http://127.0.0.1:5174',
    browserName: 'chromium',
    channel: 'chrome',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
