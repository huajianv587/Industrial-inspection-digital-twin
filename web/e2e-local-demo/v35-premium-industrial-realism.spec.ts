import { expect, test } from '@playwright/test'

const demoRunId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V35-PREMIUM-INDUSTRIAL-REALISM'

test('v35 premium scene keeps industrial detail and synchronized evidence in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.getByText(demoRunId, { exact: true }).first()).toBeVisible()
  await expect(page.locator('.latest-run-panel')).toContainText('10 / 10')
  await page.getByRole('button', { name: '查看任务详情' }).click()
  await expect(page.getByRole('heading', { name: demoRunId }).last()).toBeVisible()

  const scene = page.locator('.scene-viewport')
  await expect(page.locator('.scene-camera-button')).toHaveCount(64)
  await expect(page.locator('.scene-integrity-strip')).toContainText('已校验')
  await expect(page.locator('.scene-telemetry-overlay')).toContainText('数字孪生联动层')
  await expect(scene).toHaveAttribute('data-scene-overlay', 'active')
  await expect.poll(() => page.locator('.scene-camera-preview img').evaluate((image) => {
    const element = image as HTMLImageElement
    return element.complete && element.naturalWidth === 768 && element.naturalHeight === 480
  })).toBe(true)

  await page.getByRole('heading', { name: '同步巡检回放' }).scrollIntoViewIfNeeded()
  await expect(page.locator('.replay-feed-card')).toHaveCount(2)
  await expect(page.locator('.replay-feed-card').nth(0).locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(page.locator('.replay-feed-card').nth(1).locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(page.locator('.replay-source-badge')).toContainText('48 帧')
  await expect(page.locator('.replay-evidence-panel')).toContainText('双路已配对')

  await page.getByRole('button', { name: '回到起点' }).click()
  await page.getByRole('button', { name: '下一帧' }).click()
  await expect(page.locator('.realtime-camera-osd-bottom strong').first()).toContainText('F002 / F048')
  await expect(page.locator('.scene-telemetry-strip')).toContainText('#005')
  await expect.poll(() => page.locator('.scene-viewport').getAttribute('data-sync-frame')).toBe('5')
  await expect(page.locator('.scene-telemetry-strip')).toContainText('已同步')

  await page.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('button', { name: 'EN', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()
  await page.getByRole('button', { name: 'View mission details' }).click()
  await expect(page.getByRole('heading', { name: 'Synchronized inspection replay' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Close', exact: true }).last()).toBeVisible()
  expect(pageErrors).toEqual([])
})
