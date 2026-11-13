import { expect, test } from '@playwright/test'

test('v39 keeps console sections shareable and modal focus recoverable in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') pageErrors.push(message.text())
  })

  await page.goto('/console?view=diagnostics')
  await expect(page.getByRole('heading', { name: /点位诊断|Waypoint diagnostics/ })).toBeVisible()
  await expect(page).toHaveURL(/\/console\?view=diagnostics$/)

  await page.getByRole('button', { name: /运行指挥|Operations/ }).first().click()
  await expect(page).toHaveURL(/\/console\/?$/)

  await page.goto('/console?view=audit')
  await expect(page).toHaveURL(/\/console\?view=audit$/)
  await expect(page.getByRole('heading', { name: /审计记录|Audit trail/ })).toBeVisible()
  await page.goto('/console')

  const missionRow = page.locator('tr.clickable-row').filter({ hasText: 'RUN-V38-HQ-SMOOTH-STREAM' })
  const missionDetailsButton = missionRow.getByRole('button', { name: /查看任务详情|View mission details/ })
  await missionDetailsButton.focus()
  await missionDetailsButton.click()
  await expect(page.getByRole('dialog', { name: /RUN-V38-HQ-SMOOTH-STREAM/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: /RUN-V38-HQ-SMOOTH-STREAM/ })).toHaveCount(0)
  await expect(missionDetailsButton).toBeFocused()

  const createMissionButton = page.getByRole('button', { name: /创建巡检|New inspection/ })
  await createMissionButton.focus()
  await createMissionButton.click()
  const createDialog = page.getByRole('dialog').filter({ hasText: /创建巡检任务|Create inspection mission/ })
  await expect(createDialog).toBeVisible()
  await page.keyboard.press('Shift+Tab')
  await expect(createDialog.locator('button[type="submit"]')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(createDialog.locator('.modal-header .icon-button')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(createDialog).toHaveCount(0)
  await expect(createMissionButton).toBeFocused()

  expect(pageErrors).toEqual([])
})
