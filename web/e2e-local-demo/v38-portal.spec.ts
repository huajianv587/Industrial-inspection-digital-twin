import { expect, test } from '@playwright/test'

test('v38 portal exposes bilingual site-plan navigation and a working console handoff in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/overview')
  await expect(page).toHaveURL(/\/overview\/?$/)
  await expect(page.getByRole('heading', { name: '工业巡检平台' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '站点配置路线' })).toBeVisible()
  await expect(page.locator('.project-site-plan-stop')).toHaveCount(10)

  const routePath = await page.locator('.project-plan-route').getAttribute('d')
  expect(routePath || '').toMatch(/L.*L.*L/)

  await page.locator('.project-site-plan-stop').first().click()
  await expect(page.locator('.project-plan-hud')).toBeVisible()
  await expect(page.locator('.project-plan-hud')).toContainText('WP_01_PIPE')

  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Industrial Inspection Platform' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  const portalCjkText = await page.locator('body').evaluate((body) => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
    const matches: string[] = []
    while (walker.nextNode()) {
      const node = walker.currentNode
      const parent = node.parentElement
      if (!parent || parent.closest('.project-language') || !parent.getClientRects().length) continue
      const text = node.textContent?.trim() || ''
      if (/[\u3400-\u9fff]/.test(text)) matches.push(text)
    }
    return matches
  })
  expect(portalCjkText).toEqual([])
  await expect(page.locator('a[href="/console"]').first()).toBeVisible()

  await page.locator('a[href="/console"]').first().click()
  await expect(page).toHaveURL(/\/console\/?$/)
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()
  const consoleCjkText = await page.locator('body').evaluate((body) => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
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
  expect(consoleCjkText).toEqual([])
  expect(pageErrors).toEqual([])
})
