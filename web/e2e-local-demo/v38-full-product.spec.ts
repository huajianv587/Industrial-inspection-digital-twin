import { expect, test } from '@playwright/test'

const runId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V38-HQ-SMOOTH-STREAM'

test('v38 exposes the complete industrial product workflow in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') pageErrors.push(message.text())
  })

  await page.goto('/')
  const missionRow = page.getByRole('row', { name: new RegExp(runId) })
  await expect(missionRow).toBeVisible()
  await missionRow.getByRole('button', { name: '查看任务详情' }).click()
  await expect(page.getByRole('heading', { name: runId }).last()).toBeVisible()

  const scene = page.locator('.scene-viewport')
  await expect(scene).toHaveAttribute('data-scene-state', 'ready', { timeout: 30_000 })
  await expect(scene.locator('canvas')).toBeVisible()

  const cutawayButton = page.locator('button[data-cutaway-active]')
  await expect(cutawayButton).toHaveAttribute('data-cutaway-active', 'true')
  await cutawayButton.click()
  await expect(cutawayButton).toHaveAttribute('data-cutaway-active', 'false')
  await cutawayButton.click()
  await expect(cutawayButton).toHaveAttribute('data-cutaway-active', 'true')

  const cameraButtons = page.locator('.scene-camera-button')
  await expect(cameraButtons).toHaveCount(64)
  await expect(cameraButtons.filter({ has: page.locator('.scene-camera-icon') }).first()).toHaveClass(/selected/)
  const preview = page.locator('.scene-camera-preview img')
  await expect.poll(() => preview.getAttribute('src')).toBeTruthy()
  const firstCameraSource = await preview.getAttribute('src')
  await cameraButtons.nth(1).click()
  await expect(cameraButtons.nth(1)).toHaveClass(/selected/)
  await expect.poll(() => preview.getAttribute('src')).not.toBe(firstCameraSource)

  const replay = page.locator('.synchronized-replay')
  await replay.scrollIntoViewIfNeeded()
  await expect(replay.getByRole('heading', { name: '同步巡检回放' })).toBeVisible()
  await expect(replay.locator('.continuous-video-feed video')).toHaveCount(2)
  const workstationGeometry = await replay.evaluate((root) => {
    const map = root.querySelector('.replay-map-panel')?.getBoundingClientRect()
    const feeds = root.querySelector('.replay-feed-grid-paired')?.getBoundingClientRect()
    const cards = [...root.querySelectorAll('.replay-feed-card')].map((card) => card.getBoundingClientRect())
    return {
      map: map ? { right: map.right, y: map.y, width: map.width } : null,
      feeds: feeds ? { x: feeds.x, y: feeds.y, width: feeds.width } : null,
      cards: cards.map((card) => ({ x: card.x, y: card.y, width: card.width, height: card.height })),
    }
  })
  expect(workstationGeometry.map).not.toBeNull()
  expect(workstationGeometry.feeds).not.toBeNull()
  expect(workstationGeometry.feeds!.x).toBeGreaterThan(workstationGeometry.map!.right)
  expect(workstationGeometry.cards).toHaveLength(2)
  expect(workstationGeometry.cards[1].y).toBeGreaterThan(workstationGeometry.cards[0].y)
  expect(workstationGeometry.cards.every((card) => card.width >= 380)).toBe(true)
  const mapReadout = await replay.locator('.replay-map-readout').boundingBox()
  const floorPlan = await replay.locator('.replay-floor-plan').boundingBox()
  expect(mapReadout).not.toBeNull()
  expect(floorPlan).not.toBeNull()
  expect(mapReadout!.y + mapReadout!.height).toBeLessThanOrEqual(floorPlan!.y)
  await page.waitForFunction(() => [...document.querySelectorAll('.continuous-video-feed video')]
    .every((video) => video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA))

  const waypointFilter = replay.locator('select[aria-label="航点筛选"]')
  await waypointFilter.selectOption('WP_04_PUMP')
  await expect(replay.locator('.replay-filter-context')).toContainText('WP_04_PUMP')

  const evidenceFilter = replay.locator('select[aria-label="证据状态"]')
  await evidenceFilter.selectOption('verified')
  await expect(replay.locator('.replay-evidence-panel')).toContainText('双路已配对')
  await evidenceFilter.selectOption('all')

  const cameraFilter = replay.locator('select[aria-label="机位筛选"]')
  await cameraFilter.selectOption('robot')
  await expect(replay.locator('.replay-feed-card')).toHaveCount(1)
  await expect(replay.locator('.replay-feed-card').first()).toContainText('机器人头顶 RGB 视频流')
  await cameraFilter.selectOption('cctv')
  await expect(replay.locator('.replay-feed-card')).toHaveCount(1)
  await expect(replay.locator('.replay-feed-card').first()).toContainText('仓库固定摄像头视角')
  await cameraFilter.selectOption('paired')
  await expect(replay.locator('.replay-feed-card')).toHaveCount(2)

  await replay.getByRole('button', { name: '回到起点' }).click()
  const frameReadout = replay.locator('.realtime-camera-osd-bottom strong').first()
  await expect(frameReadout).toContainText('F001')
  const initialFrame = await frameReadout.innerText()
  await replay.getByRole('button', { name: '下一帧' }).click()
  await expect.poll(() => frameReadout.innerText()).not.toBe(initialFrame)
  await expect(frameReadout).toContainText('F002')

  const speedControl = replay.locator('.replay-speed-control')
  await speedControl.getByRole('button', { name: '0.25x', exact: true }).click()
  await expect(speedControl.getByRole('button', { name: '0.25x', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await speedControl.getByRole('button', { name: '0.5x', exact: true }).click()
  await expect(speedControl.getByRole('button', { name: '0.5x', exact: true })).toHaveAttribute('aria-pressed', 'true')

  const popupPromise = page.waitForEvent('popup')
  await replay.getByRole('button', { name: '查看原图' }).first().click()
  const evidencePopup = await popupPromise
  await expect.poll(() => evidencePopup.url()).toMatch(/^blob:/)
  await evidencePopup.close()

  await page.getByRole('button', { name: '关闭', exact: true }).last().click()
  await page.getByRole('button', { name: 'EN', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()

  await page.getByRole('row', { name: new RegExp(runId) })
    .getByRole('button', { name: 'View mission details' }).click()
  await expect(page.getByRole('heading', { name: 'Synchronized inspection replay' })).toBeVisible()
  await expect(page.locator('.scene-camera-rail')).toContainText('Camera views')
  await expect(page.locator('.replay-workbench-bar')).toContainText('Evidence workbench')
  await expect(page.locator('.replay-floor-plan')).toHaveAttribute('aria-label', /Plant top-down plan/)
  await expect(page.locator('.replay-route-safety-badge')).toContainText('Collision-safe aisle planning')
  await expect(page.locator('body')).not.toContainText('同步巡检回放')
  const detailCjkText = await page.locator('.detail-panel').evaluate((panel) => {
    const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT)
    const matches: string[] = []
    while (walker.nextNode()) {
      const node = walker.currentNode
      const parent = node.parentElement
      if (!parent || parent.closest('.language-switch') || !parent.getClientRects().length) continue
      const text = node.textContent?.trim() || ''
      if (/[\u3400-\u9fff]/.test(text)) matches.push(text)
    }
    return matches
  })
  expect(detailCjkText).toEqual([])

  expect(pageErrors).toEqual([])
})
