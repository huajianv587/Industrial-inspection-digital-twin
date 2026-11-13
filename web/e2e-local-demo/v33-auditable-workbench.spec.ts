import { expect, test } from '@playwright/test'

const demoRunId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V33-AUDITABLE-EVIDENCE-WORKBENCH'

test('v33 auditable workbench keeps scene, route, camera pair, and evidence metadata aligned', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.getByText(demoRunId, { exact: true }).first()).toBeVisible()
  await expect(page.locator('.latest-run-panel')).toContainText('10 / 10')
  await page.getByRole('button', { name: '查看任务详情' }).click()
  await expect(page.getByRole('heading', { name: demoRunId }).last()).toBeVisible()

  const scene = page.locator('.scene-viewport')
  const cameras = page.locator('.scene-camera-button')
  await expect(cameras).toHaveCount(64)
  await expect(page.locator('.scene-camera-group-heading')).toHaveCount(5)
  await expect(page.locator('.scene-integrity-strip')).toContainText('已校验')
  const preview = page.locator('.scene-camera-preview img')
  await expect.poll(() => preview.evaluate((image) => {
    const element = image as HTMLImageElement
    return element.complete && element.naturalWidth === 768 && element.naturalHeight === 480
  })).toBe(true)
  const firstSource = await preview.getAttribute('src')
  await cameras.nth(1).click()
  await expect(cameras.nth(1)).toHaveClass(/selected/)
  await expect.poll(() => preview.getAttribute('src')).not.toBe(firstSource)
  await expect.poll(() => preview.evaluate((image) => {
    const element = image as HTMLImageElement
    return element.complete && element.naturalWidth === 768 && element.naturalHeight === 480
  })).toBe(true)

  await page.getByRole('heading', { name: '同步巡检回放' }).scrollIntoViewIfNeeded()
  await expect(page.locator('.replay-workbench-label')).toContainText('证据工作台')
  await expect(page.locator('.replay-workbench-bar select')).toHaveCount(3)
  const robotFeed = page.locator('.replay-feed-card').nth(0)
  const cctvFeed = page.locator('.replay-feed-card').nth(1)
  await expect(robotFeed.locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(cctvFeed.locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(page.locator('.replay-source-badge')).toContainText('48 帧')
  await expect(page.locator('.replay-evidence-panel')).toContainText('双路已配对')
  await expect(page.locator('.replay-evidence-panel')).toContainText('512 × 288')

  const waypointFilter = page.locator('select[aria-label="航点筛选"]')
  await waypointFilter.selectOption('WP_04_PUMP')
  await expect(page.locator('.replay-filter-context')).toContainText('WP_04_PUMP')
  const cameraFilter = page.locator('select[aria-label="机位筛选"]')
  await cameraFilter.selectOption('cctv')
  await expect(page.locator('.replay-feed-card')).toHaveCount(1)
  await cameraFilter.selectOption('paired')
  await expect(page.locator('.replay-feed-card')).toHaveCount(2)

  const labels = page.locator('.realtime-camera-osd-bottom strong')
  await page.getByRole('button', { name: '回到起点' }).click()
  await expect(labels.nth(0)).toContainText('F001 / F048')
  await expect(labels.nth(1)).toHaveText(await labels.nth(0).innerText())
  await page.getByRole('button', { name: '下一帧' }).click()
  await expect.poll(() => labels.nth(0).innerText()).toContain('F002 / F048')
  await expect(labels.nth(1)).toHaveText(await labels.nth(0).innerText())

  await page.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('button', { name: 'EN', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('同步巡检回放')
  await page.getByRole('button', { name: 'View mission details' }).click()
  await expect(page.getByRole('heading', { name: 'Synchronized inspection replay' })).toBeVisible()
  await expect(page.locator('.replay-workbench-label')).toContainText('Evidence workbench')
  await expect(page.locator('.replay-evidence-panel')).toContainText('Pair verified')
  await page.getByRole('button', { name: 'Close', exact: true }).last().click()
  await page.getByRole('button', { name: '中文', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')

  await page.getByRole('button', { name: '查看任务详情' }).click()
  await expect(scene.locator('canvas')).toBeVisible()
  expect(pageErrors).toEqual([])
})
