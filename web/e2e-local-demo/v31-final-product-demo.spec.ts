import { expect, test } from '@playwright/test'

const demoRunId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V31-FINAL-PRODUCT-DEMO-SUCCESS'

async function countChangedPixels(page: import('@playwright/test').Page, before: Buffer, after: Buffer) {
  return page.evaluate(async ({ beforeBase64, afterBase64 }) => {
    const decode = async (base64: string) => {
      const image = new Image()
      image.src = `data:image/png;base64,${base64}`
      await image.decode()
      const canvas = document.createElement('canvas')
      canvas.width = image.naturalWidth
      canvas.height = image.naturalHeight
      const context = canvas.getContext('2d')
      if (!context) return null
      context.drawImage(image, 0, 0)
      return { data: context.getImageData(0, 0, canvas.width, canvas.height).data, width: canvas.width, height: canvas.height }
    }

    const first = await decode(beforeBase64)
    const second = await decode(afterBase64)
    if (!first || !second || first.width !== second.width || first.height !== second.height) return 0
    let changed = 0
    for (let y = 2; y < first.height - 2; y += 2) {
      for (let x = 2; x < first.width - 2; x += 2) {
        const offset = (y * first.width + x) * 4
        const delta = Math.max(
          Math.abs(first.data[offset] - second.data[offset]),
          Math.abs(first.data[offset + 1] - second.data[offset + 1]),
          Math.abs(first.data[offset + 2] - second.data[offset + 2]),
        )
        if (delta > 24) changed += 1
      }
    }
    return changed
  }, { beforeBase64: before.toString('base64'), afterBase64: after.toString('base64') })
}

async function expectEnglishSurface(page: import('@playwright/test').Page) {
  const visibleText = await page.locator('body').innerText()
  expect(visibleText.replaceAll('中文', '')).not.toMatch(/[\u4e00-\u9fff]/)
}

test('final product demo completes with a rendered factory and synchronized camera feeds', async ({ page }, testInfo) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.getByText(demoRunId, { exact: true }).first())
    .toBeVisible()
  await expect(page.locator('.latest-run-panel')).toContainText('10 / 10')
  await expect(page.locator('.latest-run-panel')).toContainText('0')
  await expect(page.locator('.nav-item').filter({ hasText: '工单复核' })).toContainText('0')

  await page.getByRole('button', { name: '查看任务详情' }).click()
  await expect(page.getByRole('heading', { name: demoRunId }).last())
    .toBeVisible()
  await expect(page.getByText('无需复核', { exact: true })).toBeVisible()
  await expect(page.locator('.waypoint-result')).toHaveCount(10)
  await expect(page.locator('.severity-pill-normal')).toHaveCount(10)

  const scene = page.locator('.scene-viewport')
  const canvas = scene.locator('canvas')
  await expect(canvas).toBeVisible()
  const cutawayToggle = page.getByRole('button', { name: '显示屋顶' })
  await expect(cutawayToggle).toHaveAttribute('aria-pressed', 'true')
  await expect(scene.locator('.scene-viewport-state')).toHaveCount(0, { timeout: 45_000 })
  await expect.poll(() => canvas.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return bounds.width > 300 && bounds.height > 250
      && element.width > 0 && element.height > 0
  })).toBe(true)
  await page.getByRole('heading', { name: '虚拟工厂 3D 场景' }).scrollIntoViewIfNeeded()
  await expect.poll(async () => {
    const image = await scene.screenshot()
    return page.evaluate(async (base64) => {
      const bitmap = new Image()
      bitmap.src = `data:image/png;base64,${base64}`
      await bitmap.decode()
      const sample = document.createElement('canvas')
      sample.width = bitmap.naturalWidth
      sample.height = bitmap.naturalHeight
      const context = sample.getContext('2d')
      if (!context) return 0
      context.drawImage(bitmap, 0, 0)
      const { data, width, height } = context.getImageData(0, 0, sample.width, sample.height)
      const background = [data[0], data[1], data[2]]
      let scenePixels = 0
      for (let y = 2; y < height - 2; y += 2) {
        for (let x = 2; x < width - 2; x += 2) {
          const offset = (y * width + x) * 4
          if (Math.max(
            Math.abs(data[offset] - background[0]),
            Math.abs(data[offset + 1] - background[1]),
            Math.abs(data[offset + 2] - background[2]),
          ) > 28) scenePixels += 1
        }
      }
      return scenePixels
    }, image.toString('base64'))
  }, { timeout: 45_000, intervals: [500, 1000, 2000] }).toBeGreaterThan(1000)
  const cutawayBefore = await scene.screenshot({ path: testInfo.outputPath('chrome-factory-cutaway.png') })
  await cutawayToggle.click()
  await expect(page.getByRole('button', { name: '室内剖视' })).toHaveAttribute('aria-pressed', 'false')
  await page.waitForTimeout(250)
  const roofVisible = await scene.screenshot()
  expect(await countChangedPixels(page, cutawayBefore, roofVisible)).toBeGreaterThan(250)
  await page.getByRole('button', { name: '室内剖视' }).click()
  await expect(page.getByRole('button', { name: '显示屋顶' })).toHaveAttribute('aria-pressed', 'true')

  const cameraButtons = page.locator('.scene-camera-button')
  await expect(cameraButtons).toHaveCount(64)
  await expect.poll(() => page.locator('.scene-camera-preview img').evaluate((image) => {
    const element = image as HTMLImageElement
    return element.complete && element.naturalWidth > 0 && element.naturalHeight > 0
  })).toBe(true)
  const firstCamera = await page.locator('.scene-camera-preview img').getAttribute('src')
  await cameraButtons.nth(1).click()
  await expect(cameraButtons.nth(1)).toHaveClass(/selected/)
  await expect.poll(() => page.locator('.scene-camera-preview img').getAttribute('src'))
    .not.toBe(firstCamera)

  await page.getByRole('heading', { name: '同步巡检回放' }).scrollIntoViewIfNeeded()
  const robotFeed = page.locator('.replay-feed-card').nth(0)
  const cctvFeed = page.locator('.replay-feed-card').nth(1)
  await expect(robotFeed.locator('img')).toBeVisible()
  await expect(cctvFeed.locator('img')).toBeVisible()
  await expect(robotFeed.locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(cctvFeed.locator('img')).toHaveJSProperty('naturalWidth', 512)
  await expect(page.locator('.replay-source-badge')).toContainText('48 帧')

  const syncLabels = page.locator('.realtime-camera-osd-bottom strong')
  await expect(syncLabels).toHaveCount(2)
  const returnToStart = page.getByRole('button', { name: '回到起点' })
  const nextFrame = page.getByRole('button', { name: '下一帧' })
  await returnToStart.click()
  await expect(syncLabels.nth(0)).toContainText('F001 / F048')
  await expect(syncLabels.nth(1)).toHaveText(await syncLabels.nth(0).innerText())
  await nextFrame.click()
  await expect(syncLabels.nth(1)).toHaveText(await syncLabels.nth(0).innerText())
  await expect(syncLabels.nth(0)).toContainText('F001 / F048')

  await page.getByRole('button', { name: '0.25x', exact: true }).click()
  await expect(page.getByRole('button', { name: '0.25x', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '0.5x', exact: true }).click()
  await expect(page.getByRole('button', { name: '0.5x', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '1x', exact: true }).click()
  await expect(page.getByRole('button', { name: '1x', exact: true })).toHaveAttribute('aria-pressed', 'true')

  const timeline = page.getByRole('slider', { name: '同步回放进度' })
  await timeline.fill('5')
  await expect(syncLabels.nth(0)).toContainText('F002 / F048')
  await expect(syncLabels.nth(1)).toHaveText(await syncLabels.nth(0).innerText())
  await expect(robotFeed.locator('header small')).toHaveText('F002')
  await expect(cctvFeed.locator('header small')).toContainText('F0002')
  const box = await timeline.boundingBox()
  expect(box).not.toBeNull()
  if (box) {
    await page.mouse.move(box.x + 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * 0.52, box.y + box.height / 2, { steps: 8 })
    await page.mouse.up()
  }
  await expect(timeline).not.toHaveValue('0')
  await expect(syncLabels.nth(0)).toHaveText(await syncLabels.nth(1).innerText())
  await expect(syncLabels.nth(0)).toContainText('/ F048')

  expect(pageErrors).toEqual([])
})

test('enterprise console switches the complete product surface between Chinese and English', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.getByText(demoRunId, { exact: true }).first()).toBeVisible()

  await page.getByRole('button', { name: 'EN', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page).toHaveTitle('Inspection Operations Console')
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()
  await expect(page.locator('.sidebar-site')).toContainText('Example Continuous Process Plant')
  await expect(page.locator('.sidebar-site')).not.toContainText('示例连续工艺车间')

  await page.getByRole('button', { name: 'View mission details' }).click()
  await expect(page.getByRole('heading', { name: 'Virtual factory 3D scene' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Synchronized inspection replay' })).toBeVisible()
  await expect(page.getByText('Robot-head RGB stream', { exact: true })).toBeVisible()
  await expect(page.getByText('Warehouse fixed camera', { exact: true })).toBeVisible()
  await expect(page.locator('.replay-source-badge')).toContainText('Synced image stream')
  await expect(page.locator('.replay-source-badge')).not.toContainText('同步图像流')
  await expectEnglishSurface(page)

  await page.getByRole('button', { name: 'Close', exact: true }).last().click()
  await page.getByRole('button', { name: 'Scene & execution' }).click()
  await expect(page.getByRole('heading', { name: 'Industrial asset register & field readiness' })).toBeVisible()
  await expect(page.locator('.asset-register-panel')).toContainText('Steam header')
  await expect(page.locator('.asset-register-panel')).not.toContainText('蒸汽主管道')

  await page.getByRole('button', { name: '中文', exact: true }).first().click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(page).toHaveTitle('巡检运营控制台')
  await expect(page.getByRole('heading', { name: '工业资产台账与现场就绪状态' })).toBeVisible()
  await expect(page.locator('.asset-register-panel')).toContainText('蒸汽主管道')
  await expect(page.locator('.asset-register-panel')).not.toContainText('Steam header')

  expect(pageErrors).toEqual([])
})

test('overview landing page keeps its complete bilingual system narrative', async ({ page }) => {
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: '工业巡检平台', exact: true })).toBeVisible()
  await expect(page.locator('.project-home')).toContainText('仅合成数据')

  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page).toHaveTitle('Industrial Inspection Platform | Overview')
  await expect(page.getByRole('heading', { name: 'Industrial Inspection Platform', exact: true })).toBeVisible()
  await expect(page.locator('.project-home')).toContainText('SYNTHETIC ONLY')
  await expect(page.locator('.project-hero')).toContainText('NOT A FIELD DEPLOYMENT')
  await expect(page.locator('.project-hero')).not.toContainText('非现场部署画面')
  await expectEnglishSurface(page)
})

test('overview landing page remains usable on a narrow Chrome viewport', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const page = await context.newPage()

  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: '工业巡检平台', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await expect(page.locator('.project-header-actions')).toBeVisible()
  await expect(page.locator('.project-hero')).toBeVisible()

  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Industrial Inspection Platform', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)

  await context.close()
})
