import { expect, test } from '@playwright/test'

const anomalyRunId = process.env.LOCAL_DEMO_RUN_ID || 'RUN-V37-SYNTHETIC-ANOMALY'

test('synthetic anomaly stays traceable through review and audit in Chrome', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.goto('/')
  await expect(page.getByText(anomalyRunId, { exact: true }).first()).toBeVisible()

  const missionRow = page.getByRole('row', { name: new RegExp(anomalyRunId) })
  await missionRow.getByRole('button', { name: '查看任务详情' }).click()
  await expect(page.getByRole('heading', { name: anomalyRunId }).last()).toBeVisible()
  await expect(page.getByText('隔离合成异常闭环', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).last().click()

  await page.getByRole('button', { name: /工单复核/ }).click()
  await expect(page.getByRole('heading', { name: '人工复核队列' })).toBeVisible()
  await expect(page.locator('.work-order-row')).toHaveCount(5)
  await expect(page.locator('.integration-state')).toContainText('EAM 未接入')

  const reviewedOrders = page.locator('.work-order-row').filter({ hasText: '已确认' })
  let reviewedTicketId = ''
  if (await reviewedOrders.count() === 0) {
    const pendingOrder = page.locator('.work-order-row').filter({ hasText: '待复核' }).first()
    reviewedTicketId = await pendingOrder.locator('.order-meta span').first().innerText()
    await pendingOrder.getByLabel(`${reviewedTicketId} 填写复核意见`).fill('已查看合成证据，确认进入工单闭环。')
    await pendingOrder.getByRole('button', { name: '确认', exact: true }).click()
    const submittedOrder = page.locator('.work-order-row').filter({ hasText: reviewedTicketId })
    await expect(submittedOrder.locator('.review-state')).toHaveText('已确认')
  } else {
    reviewedTicketId = await reviewedOrders.first().locator('.order-meta span').first().innerText()
  }

  const reviewedOrder = page.locator('.work-order-row').filter({ hasText: reviewedTicketId })
  await expect(reviewedOrder).toContainText('已确认')
  await expect(reviewedOrder).toContainText('尚未提交 EAM')
  await expect(reviewedOrder.getByRole('button', { name: '提交 EAM', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: '审计记录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '系统审计轨迹' })).toBeVisible()
  await expect(page.getByText('WORK_ORDER_REVIEWED', { exact: true })).toBeVisible()
  expect(pageErrors).toEqual([])
})
