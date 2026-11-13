import { expect, test } from '@playwright/test'

const runId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V38-HQ-SMOOTH-STREAM'

test('v38 renders a smooth synchronized stream and collision-free route labels in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  const threeModuleRequests: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') pageErrors.push(message.text())
  })
  page.on('request', (request) => {
    const url = request.url()
    if (/\/node_modules\/(?:\.vite\/deps\/)?three(?:\/|\.js)|\/assets\/three-scene-/.test(url)) {
      threeModuleRequests.push(url)
    }
  })

  await page.goto('/')
  const missionRow = page.locator('tr.clickable-row').filter({ hasText: runId })
  await expect(missionRow).toBeVisible()
  expect(threeModuleRequests).toEqual([])
  await missionRow.getByRole('button', { name: '查看任务详情' }).click()

  await expect(page.getByRole('heading', { name: runId }).last()).toBeVisible()
  await expect(page.locator('.scene-viewport')).toHaveAttribute('data-scene-state', 'ready', { timeout: 30_000 })
  expect(threeModuleRequests.length).toBeGreaterThan(0)
  const replay = page.locator('.synchronized-replay')
  await expect(replay.locator('.continuous-video-feed video')).toHaveCount(2)
  const pairedFeeds = replay.locator('.replay-feed-grid-paired')
  await pairedFeeds.scrollIntoViewIfNeeded()
  await expect(pairedFeeds).toBeInViewport()
  await page.waitForFunction(() => [...document.querySelectorAll('.continuous-video-feed video')]
    .every((video) => video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !video.paused))

  await expect(replay.locator('.realtime-camera-osd-bottom b').first()).toContainText('FPS')
  await expect.poll(async () => replay.locator('.realtime-camera-osd-bottom b').evaluateAll((nodes) => nodes
    .every((node) => !/^0 FPS$/.test(node.textContent?.trim() || ''))))
    .toBe(true)

  const mapGeometry = await replay.locator('.replay-floor-plan').evaluate((svg) => {
    const box = (element: Element) => {
      const { x, y, width, height } = (element as SVGTextElement).getBBox()
      return { x, y, width, height }
    }
    return {
      labels: [...svg.querySelectorAll('[data-waypoint-label="true"]')].map(box),
      waypointLabelBadges: [...svg.querySelectorAll('[data-waypoint-label-bg="true"]')].map(box),
      waypointLeaderLines: [...svg.querySelectorAll('[data-waypoint-label-line="true"]')],
      equipmentLabels: [...svg.querySelectorAll('.replay-equipment-label')].map(box),
      zoneLabels: [...svg.querySelectorAll('.replay-floor-zone text')].map(box),
      waypointMarkers: [...svg.querySelectorAll('.replay-waypoint circle:first-child')].map(box),
    }
  })
  const routeLabels = mapGeometry.labels
  expect(routeLabels).toHaveLength(10)
  expect(mapGeometry.waypointLabelBadges).toHaveLength(10)
  expect(mapGeometry.waypointLeaderLines).toHaveLength(10)
  const boxesDoNotOverlap = (left: { x: number; y: number; width: number; height: number }, right: { x: number; y: number; width: number; height: number }) => {
    const overlapWidth = Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x)
    const overlapHeight = Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y)
    return Math.max(0, overlapWidth) * Math.max(0, overlapHeight) <= 1
  }
  const osdItems = await page.locator('.scene-osd-meta > span').evaluateAll((elements) => elements.map((element) => {
    const { x, y, width, height } = element.getBoundingClientRect()
    return { x, y, width, height }
  }))
  expect(osdItems).toHaveLength(4)
  expect(new Set(osdItems.map((item) => Math.round(item.x))).size).toBe(2)
  expect(new Set(osdItems.map((item) => Math.round(item.y))).size).toBe(2)
  for (let index = 0; index < osdItems.length; index += 1) {
    for (let other = index + 1; other < osdItems.length; other += 1) {
      expect(boxesDoNotOverlap(osdItems[index], osdItems[other])).toBe(true)
    }
  }
  for (const selector of ['.scene-osd-readouts > span', '.scene-osd-footer > span']) {
    const items = await page.locator(selector).evaluateAll((elements) => elements.map((element) => {
      const { x, y, width, height } = element.getBoundingClientRect()
      return { x, y, width, height }
    }))
    expect(items).toHaveLength(3)
    expect(new Set(items.map((item) => Math.round(item.x))).size).toBe(3)
    for (let index = 0; index < items.length; index += 1) {
      for (let other = index + 1; other < items.length; other += 1) {
        expect(boxesDoNotOverlap(items[index], items[other])).toBe(true)
      }
    }
  }
  for (let index = 0; index < routeLabels.length; index += 1) {
    for (let other = index + 1; other < routeLabels.length; other += 1) {
      expect(boxesDoNotOverlap(routeLabels[index], routeLabels[other])).toBe(true)
    }
    for (const obstacle of [...mapGeometry.equipmentLabels, ...mapGeometry.zoneLabels, ...mapGeometry.waypointMarkers]) {
      expect(boxesDoNotOverlap(routeLabels[index], obstacle)).toBe(true)
    }
  }
  for (let index = 0; index < mapGeometry.waypointLabelBadges.length; index += 1) {
    for (let other = index + 1; other < mapGeometry.waypointLabelBadges.length; other += 1) {
      expect(boxesDoNotOverlap(mapGeometry.waypointLabelBadges[index], mapGeometry.waypointLabelBadges[other])).toBe(true)
    }
    for (const obstacle of [...mapGeometry.equipmentLabels, ...mapGeometry.zoneLabels, ...mapGeometry.waypointMarkers]) {
      expect(boxesDoNotOverlap(mapGeometry.waypointLabelBadges[index], obstacle)).toBe(true)
    }
  }
  for (const equipmentLabel of mapGeometry.equipmentLabels) {
    for (const obstacle of [...mapGeometry.zoneLabels, ...mapGeometry.waypointMarkers, ...routeLabels]) {
      expect(boxesDoNotOverlap(equipmentLabel, obstacle)).toBe(true)
    }
  }
  for (const zoneLabel of mapGeometry.zoneLabels) {
    for (const marker of mapGeometry.waypointMarkers) {
      expect(boxesDoNotOverlap(zoneLabel, marker)).toBe(true)
    }
  }
  await expect(replay.locator('.replay-waypoint > text:not([data-waypoint-label="true"])')).toHaveCount(0)

  await page.waitForTimeout(1_000)
  const videoState = await replay.locator('.continuous-video-feed video').evaluateAll((elements) => {
    const videos = elements as HTMLVideoElement[]
    return {
      drift: Math.abs(videos[0].currentTime - videos[1].currentTime),
      playbackRates: videos.map((video) => video.playbackRate),
    }
  })
  expect(videoState.drift).toBeLessThan(0.1)
  expect(videoState.playbackRates).toEqual([0.5, 0.5])
  await expect.poll(async () => replay.locator('.realtime-camera-osd-bottom b').evaluateAll((nodes) => nodes
    .map((node) => Number(node.textContent?.match(/\d+/)?.[0] || 0) >= 24)))
    .toEqual([true, true])
  await page.waitForFunction(() => [...document.querySelectorAll('.continuous-video-feed video')]
    .every((video) => video.currentTime >= 2.5))
  await page.waitForTimeout(250)
  const cameraFrameRates = await replay.locator('.continuous-video-feed video').evaluateAll((elements) => Promise.all(
    (elements as HTMLVideoElement[]).map((video) => new Promise<{ fps: number; dropped: number }>((resolve) => {
      const startedAt = performance.now()
      const qualityBefore = video.getVideoPlaybackQuality()
      window.setTimeout(() => {
        const elapsed = performance.now() - startedAt
        const qualityAfter = video.getVideoPlaybackQuality()
        const totalFrames = qualityAfter.totalVideoFrames - qualityBefore.totalVideoFrames
        const dropped = qualityAfter.droppedVideoFrames - qualityBefore.droppedVideoFrames
        resolve({ fps: Math.max(0, totalFrames - dropped) * 1_000 / elapsed, dropped })
      }, 2_000)
    })),
  ))
  expect(cameraFrameRates).toHaveLength(2)
  expect(cameraFrameRates.every((sample) => sample.fps >= 24), `Camera presentation samples: ${JSON.stringify(cameraFrameRates)}`).toBe(true)
  await expect(replay.locator('.realtime-camera-osd-top')).toHaveCount(2)
  await expect(replay.locator('.realtime-camera-osd-bottom')).toHaveCount(2)
  await expect(replay.locator('.replay-feed-sync, .replay-feed-image > b')).toHaveCount(0)
  await expect(page.locator('.scene-osd-meta')).toContainText('THREE.JS / WEBGL')
  await expect(page.locator('.scene-osd-meta')).not.toContainText('丢包率')
  expect(pageErrors).toEqual([])
})
