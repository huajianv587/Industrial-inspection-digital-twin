import { readFileSync } from 'node:fs'
import { expect, test, type Page, type Route } from '@playwright/test'

const createdAt = '2026-10-21T08:00:00+00:00'
const site = {
  site_id: 'SIM-FACTORY-001',
  site_name: '示例工厂巡检区域',
  robot: { robot_id: 'unitree-sim-01', model: 'Unitree Go2 (simulated adapter)' },
  waypoints: [
    {
      waypoint_id: 'WP_01_PIPE', device_id: 'DEV-PIPE-302',
      device_name: '蒸汽主管道压力表与法兰', zone: '模拟管廊 A 区',
      position: { x: 4, y: 1, z: 0 },
    },
    {
      waypoint_id: 'WP_02_CABINET', device_id: 'DEV-CAB-108',
      device_name: '低压配电柜 4 号柜', zone: '模拟配电房 B 区',
      position: { x: 8, y: -2, z: 0 },
    },
    {
      waypoint_id: 'WP_03_PUMP', device_id: 'DEV-PUMP-021',
      device_name: '循环泵组 P-021', zone: '模拟泵房 C 区',
      position: { x: 11.5, y: 3.5, z: 0 },
    },
  ],
}
const configuredSitePlan = JSON.parse(readFileSync(
  new URL('../../configs/site.json', import.meta.url), 'utf8',
)) as { site_id: string; waypoints: typeof site.waypoints }

type Mission = {
  run_id: string
  site_id: string
  robot_id: string
  execution_backend: string
  status: string
  seed: number
  slurm_job_id: string | null
  error: string | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

type WorkOrder = {
  ticket_id: string
  run_id: string
  severity: string
  review_status: string
  payload: Record<string, unknown>
  reviewed_by: string | null
  review_decision: string | null
  review_comment: string | null
  created_at: string
  reviewed_at: string | null
  eam_submission: {
    status: 'PENDING' | 'SUBMITTED' | 'FAILED'
    attempts: number
    external_id: string | null
    submitted_at: string | null
    updated_at: string
  } | null
}

function newMission(runId: string, seed = 42): Mission {
  return {
    run_id: runId,
    site_id: site.site_id,
    robot_id: site.robot.robot_id,
    execution_backend: 'offline',
    status: 'QUEUED',
    seed,
    slurm_job_id: null,
    error: null,
    created_at: createdAt,
    updated_at: createdAt,
    finished_at: null,
  }
}

function pendingOrder(ticketId = 'SIM-WO-0001'): WorkOrder {
  return {
    ticket_id: ticketId,
    run_id: 'RUN-0000000000000001',
    severity: 'HIGH',
    review_status: 'PENDING',
    payload: {
      device_name: '蒸汽主管道压力表与法兰',
      anomaly_codes: ['MEASUREMENT_MISSING'],
      recommended_actions: ['必需测量缺失，不能判定设备正常；重新采集数据并由人工复核。'],
    },
    reviewed_by: null,
    review_decision: null,
    review_comment: null,
    created_at: createdAt,
    reviewed_at: null,
    eam_submission: null,
  }
}

async function fulfillJson(route: Route, payload: unknown, status = 200,
  headers: Record<string, string> = {}) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    headers,
    body: JSON.stringify(payload),
  })
}

async function installMocks(
  page: Page,
  roles: string[] = ['admin', 'operator', 'reviewer'],
  options: { loseFirstMissionResponse?: boolean; paginateHistory?: boolean } = {},
) {
  const missions: Mission[] = options.paginateHistory
    ? Array.from({ length: 51 }, (_, index) => newMission(`RUN-${String(51 - index).padStart(16, '0')}`))
    : []
  const workOrders = options.paginateHistory
    ? Array.from({ length: 51 }, (_, index) => pendingOrder(`SIM-WO-${String(51 - index).padStart(4, '0')}`))
    : [pendingOrder()]
  const auditHistory = options.paginateHistory
    ? Array.from({ length: 51 }, (_, index) => ({
      event_id: `e2e-audit-${String(51 - index).padStart(4, '0')}`,
      actor: 'operator@example.test',
      actor_role: 'operator',
      event_type: 'MISSION_CREATED',
      resource_type: 'mission',
      resource_id: `RUN-${String(51 - index).padStart(16, '0')}`,
      payload: {},
      created_at: createdAt,
    }))
    : []
  const missionRequests: Array<{ body: Record<string, unknown>; idempotencyKey: string | null }> = []
  const reviewRequests: Array<{ ticketId: string; body: Record<string, unknown> }> = []
  const eamRequests: string[] = []
  const apiAuthorizations: Array<string | undefined> = []
  const missionsByIdempotencyKey = new Map<string, Mission>()
  let nextMissionNumber = 1

  await page.route(/\/auth\/v1\/token\?grant_type=password$/, async (route) => {
    const user = {
      id: 'e2e-user-0001',
      aud: 'authenticated',
      role: 'authenticated',
      email: 'operator@example.test',
      email_confirmed_at: createdAt,
      app_metadata: { provider: 'email', providers: ['email'], roles },
      user_metadata: {},
      created_at: createdAt,
      updated_at: createdAt,
    }
    await fulfillJson(route, {
      access_token: 'e2e-only-access-token',
      token_type: 'bearer',
      expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 3600,
      refresh_token: 'e2e-only-refresh-token',
      user,
    })
  })

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const method = request.method()
    apiAuthorizations.push(request.headers()['authorization'])

    if (method === 'GET' && path === '/dashboard') {
      if (roles.length === 0) {
        await fulfillJson(route, { detail: { code: 'APPLICATION_ROLE_REQUIRED' } }, 403, {
          'X-Error-Code': 'APPLICATION_ROLE_REQUIRED',
        })
        return
      }
      const missionCounts = missions.reduce<Record<string, number>>((counts, mission) => {
        counts[mission.status] = (counts[mission.status] || 0) + 1
        return counts
      }, {})
      await fulfillJson(route, {
        site: { site_id: site.site_id, site_name: site.site_name },
        robot: site.robot,
        execution_backend: 'offline',
        eam_enabled: true,
        mission_counts: missionCounts,
        pending_work_orders: workOrders.filter((order) => order.review_status === 'PENDING').length,
        recent_missions: missions.slice(0, 12),
        worker: {
          status: 'not_seen', last_seen_at: null, execution_backend: null,
          instance_id: null, last_error_type: null,
        },
      })
      return
    }
    if (method === 'GET' && path === '/sites') {
      await fulfillJson(route, site)
      return
    }
    if (method === 'GET' && path === '/missions') {
      const limit = Number(url.searchParams.get('limit') || 50)
      const cursor = url.searchParams.get('cursor')
      const start = cursor === 'missions-older' ? limit : 0
      const items = missions.slice(start, start + limit)
      await fulfillJson(route, items, 200,
        start + limit < missions.length ? { 'X-Next-Cursor': 'missions-older' } : {})
      return
    }
    if (method === 'POST' && path === '/missions') {
      const body = request.postDataJSON() as Record<string, unknown>
      const idempotencyKey = request.headers()['idempotency-key'] || null
      missionRequests.push({ body, idempotencyKey })
      const existing = idempotencyKey ? missionsByIdempotencyKey.get(idempotencyKey) : null
      if (existing) {
        await fulfillJson(route, existing, 202)
        return
      }
      const mission = newMission(`RUN-${String(nextMissionNumber++).padStart(16, '0')}`,
        Number(body.seed))
      missions.unshift(mission)
      if (idempotencyKey) missionsByIdempotencyKey.set(idempotencyKey, mission)
      if (options.loseFirstMissionResponse && missionRequests.length === 1) {
        await route.abort('failed')
        return
      }
      await fulfillJson(route, mission, 202)
      return
    }
    if (method === 'GET' && /^\/missions\/RUN-[0-9A-F]{16}$/.test(path)) {
      const mission = missions.find((item) => item.run_id === path.split('/').at(-1))
      if (!mission) {
        await fulfillJson(route, { detail: 'Mission not found.' }, 404)
        return
      }
      await fulfillJson(route, {
        ...mission,
        manifest: {
          source: 'synthetic_simulation',
          software_version: '0.2.0',
          config_sha256: 'a'.repeat(64),
          site_config: site,
        },
        result: null,
      })
      return
    }
    if (method === 'POST' && /^\/work-orders\/[^/]+\/eam$/.test(path)) {
      const ticketId = path.split('/').at(-2) || ''
      eamRequests.push(ticketId)
      const order = workOrders.find((item) => item.ticket_id === ticketId)
      if (!order || order.review_decision !== 'ACKNOWLEDGED') {
        await fulfillJson(route, { detail: 'Work order is not acknowledged.' }, 422)
        return
      }
      order.eam_submission = {
        status: 'SUBMITTED', attempts: (order.eam_submission?.attempts || 0) + 1,
        external_id: `EAM-${ticketId}`, submitted_at: createdAt, updated_at: createdAt,
      }
      await fulfillJson(route, {
        ticket_id: ticketId, status: 'SUBMITTED', external_id: `EAM-${ticketId}`, idempotent_replay: false,
      })
      return
    }
    if (method === 'GET' && path === '/work-orders') {
      const limit = Number(url.searchParams.get('limit') || 50)
      const cursor = url.searchParams.get('cursor')
      const start = cursor === 'work-orders-older' ? limit : 0
      const items = workOrders.slice(start, start + limit)
      await fulfillJson(route, items, 200,
        start + limit < workOrders.length ? { 'X-Next-Cursor': 'work-orders-older' } : {})
      return
    }
    if (method === 'POST' && /^\/work-orders\/[^/]+\/review$/.test(path)) {
      const ticketId = path.split('/').at(-2) || ''
      const body = request.postDataJSON() as Record<string, unknown>
      reviewRequests.push({ ticketId, body })
      const order = workOrders.find((item) => item.ticket_id === ticketId)
      if (!order || order.review_status !== 'PENDING') {
        await fulfillJson(route, { detail: 'Work order is unavailable for review.' }, 409)
        return
      }
      order.review_status = body.decision === 'ACKNOWLEDGED' ? 'REVIEWED' : 'DISMISSED'
      order.reviewed_by = 'operator@example.test'
      order.review_decision = String(body.decision)
      order.review_comment = String(body.comment)
      order.reviewed_at = createdAt
      await fulfillJson(route, {
        ticket_id: ticketId,
        review_status: order.review_status,
        reviewed_by: order.reviewed_by,
        reviewed_at: order.reviewed_at,
      })
      return
    }
    if (method === 'GET' && path === '/audit-events') {
      const reviewEvents = reviewRequests.map((item, index) => ({
        event_id: `e2e-audit-${index + 1}`,
        actor: 'operator@example.test',
        actor_role: 'reviewer',
        event_type: 'WORK_ORDER_REVIEWED',
        resource_type: 'work_order',
        resource_id: item.ticketId,
        payload: item.body,
        created_at: createdAt,
      }))
      const events = [...reviewEvents, ...auditHistory]
      const limit = Number(url.searchParams.get('limit') || 50)
      const cursor = url.searchParams.get('cursor')
      const start = cursor === 'audit-events-older' ? limit : 0
      const items = events.slice(start, start + limit)
      await fulfillJson(route, items, 200,
        start + limit < events.length ? { 'X-Next-Cursor': 'audit-events-older' } : {})
      return
    }

    await fulfillJson(route, { detail: `Unhandled mocked API route: ${method} ${path}` }, 404)
  })

  return { missions, missionRequests, reviewRequests, eamRequests, apiAuthorizations }
}

async function signIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('邮箱').fill('operator@example.test')
  await page.getByLabel('密码').fill('local-test-only')
  await page.getByRole('button', { name: '登录', exact: true }).click()
}

async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }))
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1)
}

test('desktop project overview shows current verification and compact workflow', async ({ page }) => {
  await page.goto('/overview')

  await expect(page.getByRole('heading', { name: '工业巡检平台', level: 1 })).toBeVisible()
  const databaseStatus = page.locator('.project-state-row').nth(1)
  await expect(databaseStatus).toContainText('专用项目 schema 已核验')
  await expect(page.locator('.project-fact strong').first()).toHaveText(
    String(configuredSitePlan.waypoints.length),
  )
  await expect.poll(() => page.locator('.project-hero > img').evaluate((image) => {
    const element = image as HTMLImageElement
    return element.complete && element.naturalWidth > 0
      && getComputedStyle(element).display !== 'none'
  })).toBe(true)
  await expect(page.locator('.project-hero')).toHaveCSS('background-image', 'none')
  await expect(page.locator('.project-capability')).toHaveCount(4)
  await expect(page.locator('.project-capability-copy .project-eyebrow').first()).toHaveText('模块 01')
  await expect(page.locator('.project-site-plan')).toHaveCSS('background-color', 'rgba(8, 12, 16, 0.94)')
  await expect(page.locator('.project-site-plan-heading span')).toContainText(configuredSitePlan.site_id)
  await expect(page.locator('.project-plan-point')).toHaveCount(configuredSitePlan.waypoints.length)
  const planLegend = page.locator('.project-site-plan-legend > button')
  await expect(planLegend).toHaveCount(configuredSitePlan.waypoints.length)
  for (const [index, waypoint] of configuredSitePlan.waypoints.entries()) {
    const coordinateLabel = `X ${waypoint.position.x.toFixed(1)} / Y ${waypoint.position.y.toFixed(1)} m`
    await expect(planLegend.nth(index)).toContainText(coordinateLabel)
    await expect(page.locator('.project-plan-point').nth(index)).toHaveAttribute('aria-label', new RegExp(coordinateLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
  const renderedPoints = await page.locator('.project-plan-point').evaluateAll((nodes) => nodes.map((node) => {
    const match = node.getAttribute('transform')?.match(/translate\(([-\d.]+) ([-\d.]+)\)/)
    return match ? { x: Number(match[1]), y: Number(match[2]) } : null
  }))
  expect(renderedPoints.every((point) => point !== null)).toBe(true)
  const renderedX = renderedPoints.map((point) => point!.x)
  const renderedY = renderedPoints.map((point) => point!.y)
  const configuredX = configuredSitePlan.waypoints.map((waypoint) => waypoint.position.x)
  const configuredY = configuredSitePlan.waypoints.map((waypoint) => waypoint.position.y)
  const renderedAspect = (Math.max(...renderedX) - Math.min(...renderedX)) / (Math.max(...renderedY) - Math.min(...renderedY))
  const configuredAspect = (Math.max(...configuredX) - Math.min(...configuredX)) / (Math.max(...configuredY) - Math.min(...configuredY))
  expect(renderedAspect).toBeCloseTo(configuredAspect, 5)

  const firstWaypointButton = planLegend.first()
  const firstMapPoint = page.locator('.project-plan-point').first()
  await firstWaypointButton.hover()
  await expect(firstMapPoint).toHaveClass(/is-active/)
  await firstWaypointButton.click()
  await page.mouse.move(0, 0)
  await expect(firstWaypointButton).toHaveAttribute('aria-pressed', 'true')
  await expect(firstMapPoint).toHaveClass(/is-active/)
  await firstWaypointButton.click()
  await page.mouse.move(0, 0)
  await expect(firstWaypointButton).toHaveAttribute('aria-pressed', 'false')
  await expect(firstMapPoint).not.toHaveClass(/is-active/)
  await planLegend.nth(1).focus()
  await expect(page.locator('.project-plan-point').nth(1)).toHaveClass(/is-active/)

  const thirdMapPoint = page.locator('.project-plan-point').nth(2)
  await thirdMapPoint.click()
  await expect(planLegend.nth(2)).toHaveAttribute('aria-pressed', 'true')
  await thirdMapPoint.focus()
  await thirdMapPoint.press('Enter')
  await expect(planLegend.nth(2)).toHaveAttribute('aria-pressed', 'false')
  await page.getByRole('link', { name: '查看运行链路' }).focus()
  await expect(thirdMapPoint).not.toHaveClass(/is-active/)
  await thirdMapPoint.focus()
  await thirdMapPoint.press('Space')
  await expect(planLegend.nth(2)).toHaveAttribute('aria-pressed', 'true')

  await expect(page.locator('.project-site-plan figcaption')).toContainText('不是实时地图')
  const heroLayout = await page.locator('.project-hero-content').evaluate((container) => {
    const bounds = container.getBoundingClientRect()
    const columns = Array.from(container.children).map((child) => {
      const { left, right, top, bottom } = child.getBoundingClientRect()
      return { left, right, top, bottom }
    })
    return { bounds: { top: bounds.top, bottom: bounds.bottom }, columns }
  })
  expect(heroLayout.columns).toHaveLength(2)
  expect(heroLayout.columns[0].right).toBeLessThanOrEqual(heroLayout.columns[1].left + 1)
  const viewportWidth = page.viewportSize()?.width || 0
  const tacticalLayout = await page.locator('.project-hero-tactical').evaluate((container) => {
    const children = Array.from(container.children).map((child) => {
      const { left, right, top, bottom } = child.getBoundingClientRect()
      return { left, right, top, bottom }
    })
    return { children }
  })
  expect(tacticalLayout.children).toHaveLength(2)
  if (viewportWidth >= 1181) {
    expect(tacticalLayout.children[0].right).toBeLessThanOrEqual(tacticalLayout.children[1].left + 1)
  } else {
    expect(tacticalLayout.children[0].bottom).toBeLessThanOrEqual(tacticalLayout.children[1].top + 1)
  }
  expect(heroLayout.columns.every(({ top, bottom }) => top >= heroLayout.bounds.top && bottom <= heroLayout.bounds.bottom)).toBe(true)
  const firstWaypoint = configuredSitePlan.waypoints[0]
  const firstCoordinateLabel = `X ${firstWaypoint.position.x.toFixed(1)} / Y ${firstWaypoint.position.y.toFixed(1)} m`
  await expect(planLegend.first()).toContainText(firstCoordinateLabel)
  const firstCapabilityHeight = await page.locator('.project-capability').first()
    .evaluate((element) => element.getBoundingClientRect().height)
  expect(firstCapabilityHeight).toBeLessThan(210)
  await expect(page.locator('.project-capability-copy p').first()).toHaveCSS(
    'font-size', '13px',
  )
  await expect(page.locator('#system .project-eyebrow').first()).toBeVisible()
  await expectNoHorizontalOverflow(page)

  await page.getByRole('link', { name: '查看运行链路' }).click()
  await expect(page).toHaveURL(/#workflow$/)
  await expect(page.getByRole('heading', { name: '一条可追溯的巡检链路' })).toBeVisible()
  await expect(page.locator('.project-flow-list li')).toHaveCount(8)

  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'One traceable inspection workflow' })).toBeVisible()
  await expect(page.locator('.project-capability-copy .project-eyebrow').first()).toHaveText('MODULE 01')
  await expect(page.locator('.project-site-plan-heading span')).toContainText('Configured coordinates')
  await expect(page.locator('.project-state-row').nth(1))
    .toContainText('Dedicated project schema verified')
  await expect(page.locator('.project-site-plan figcaption')).toContainText('not a live map')
  await expect(planLegend.first()).toContainText('PIPE RACK A')
  await expect(planLegend.first()).toContainText(firstCoordinateLabel)
  await expectNoHorizontalOverflow(page)
})

test('desktop sign-in page presents operational modules beside authentication', async ({ page }) => {
  await installMocks(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '登录巡检控制台' })).toBeVisible()
  const modules = page.locator('.login-capabilities li')
  await expect(modules).toHaveCount(4)
  await expect(modules.nth(0)).toContainText('工业运行')
  await expect(modules.nth(1)).toContainText('场景与执行调度')
  await expect(modules.nth(2)).toContainText('感知与故障诊断')
  await expect(modules.nth(3)).toContainText('工单复核与审计')

  const moduleBounds = await modules.evaluateAll((items) => items.map((item) => {
    const { top, bottom, height } = item.getBoundingClientRect()
    return { top, bottom, height }
  }))
  expect(moduleBounds.every(({ height }) => height > 0)).toBe(true)
  expect(moduleBounds.every((item, index) => index === 0 || item.top >= moduleBounds[index - 1].bottom)).toBe(true)
  await expectNoHorizontalOverflow(page)
})

test('authorized operator can create a configured multi-waypoint mission', async ({ page }) => {
  const mocks = await installMocks(page, ['operator'])
  await signIn(page)

  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Site operations overview' })).toBeVisible()
  await page.getByRole('button', { name: '中文', exact: true }).click()
  await expect(page.getByRole('heading', { name: '站点运行概览' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '示例工厂巡检区域' })).toBeVisible()
  await expect(page.locator('.top-actions').getByRole('button', { name: '创建巡检' })).toBeVisible()
  await expect(page.getByRole('button', { name: '审计记录', exact: true })).toHaveCount(0)
  const latestRunPanel = page.locator('.latest-run-panel')
  await expect(latestRunPanel.getByRole('button', { name: '创建巡检' })).toBeVisible()
  const [mapPanelHeight, latestPanelHeight] = await Promise.all([
    page.locator('.site-map-panel').evaluate((element) => element.getBoundingClientRect().height),
    latestRunPanel.evaluate((element) => element.getBoundingClientRect().height),
  ])
  if ((page.viewportSize()?.width || 0) > 1080) {
    expect(latestPanelHeight).toBeLessThan(mapPanelHeight)
  } else {
    expect(latestPanelHeight).toBeGreaterThan(0)
  }
  const toolbarTop = await page.locator('.table-toolbar').evaluate((element) => element.getBoundingClientRect().top)
  expect(toolbarTop).toBeLessThan((page.viewportSize()?.width || 0) > 1080 ? 1000 : 1500)
  await expectNoHorizontalOverflow(page)

  await page.getByRole('button', { name: /工单复核/ }).click()
  await expect(page.getByRole('heading', { name: '人工复核队列' })).toBeVisible()
  await expect(page.locator('.review-actions')).toHaveCount(0)
  await page.getByRole('button', { name: /运行指挥/ }).click()

  await page.locator('.top-actions').getByRole('button', { name: '创建巡检' }).click()
  await expect(page.getByRole('heading', { name: '创建巡检任务' })).toBeVisible()
  await expect(page.getByRole('checkbox')).toHaveCount(3)
  await page.getByLabel('仿真随机种子').fill('137')
  await page.getByRole('button', { name: '创建离线任务' }).click()

  await expect(page.getByText('RUN-0000000000000001', { exact: true }).first()).toBeVisible()
  expect(mocks.missionRequests).toHaveLength(1)
  expect(mocks.missionRequests[0].body).toEqual({
    site_id: site.site_id,
    waypoint_ids: site.waypoints.map((waypoint) => waypoint.waypoint_id),
    seed: 137,
  })
  expect(mocks.missionRequests[0].idempotencyKey).toMatch(/^[0-9a-f-]{36}$/i)
  expect(mocks.apiAuthorizations.length).toBeGreaterThan(0)
  expect(mocks.apiAuthorizations.every((value) => value === 'Bearer e2e-only-access-token')).toBe(true)
  await expectNoHorizontalOverflow(page)
})

test('operator can request a local virtual-world render with the mission', async ({ page }) => {
  const mocks = await installMocks(page, ['operator'])
  await signIn(page)

  await page.locator('.top-actions').getByRole('button', { name: '创建巡检' }).click()
  await page.getByRole('switch', { name: '生成本地虚拟场景' }).check()
  await page.getByRole('button', { name: '创建离线任务' }).click()

  await expect(page.getByText('RUN-0000000000000001', { exact: true }).first()).toBeVisible()
  expect(mocks.missionRequests[0].body).toMatchObject({ render_backend: 'blender' })
  await expectNoHorizontalOverflow(page)
})

test('mission retry after a lost response reuses its idempotency key across reload', async ({ page }) => {
  const mocks = await installMocks(page, ['admin', 'operator', 'reviewer'], {
    loseFirstMissionResponse: true,
  })
  await signIn(page)
  await page.locator('.top-actions').getByRole('button', { name: '创建巡检' }).click()
  await page.getByLabel('仿真随机种子').fill('137')
  await page.getByRole('button', { name: '创建离线任务' }).click()

  await expect(page.getByText('Failed to fetch')).toBeVisible()
  expect(mocks.missions).toHaveLength(1)
  expect(mocks.missionRequests).toHaveLength(1)

  await page.reload()
  await expect(page.getByRole('heading', { name: '站点运行概览' })).toBeVisible()
  await page.locator('.top-actions').getByRole('button', { name: '创建巡检' }).click()
  await page.getByLabel('仿真随机种子').fill('137')
  await page.getByRole('button', { name: '创建离线任务' }).click()

  await expect(page.getByText('RUN-0000000000000001', { exact: true }).first()).toBeVisible()
  expect(mocks.missions).toHaveLength(1)
  expect(mocks.missionRequests).toHaveLength(2)
  expect(mocks.missionRequests[1].idempotencyKey).toBe(mocks.missionRequests[0].idempotencyKey)
})

test('reviewer acknowledges a work order with a recorded comment', async ({ page }) => {
  const mocks = await installMocks(page, ['reviewer'])
  await signIn(page)

  await expect(page.getByRole('heading', { name: '站点运行概览' })).toBeVisible()
  await expect(page.locator('.top-actions').getByRole('button', { name: '创建巡检' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '审计记录', exact: true })).toBeVisible()
  await page.getByRole('button', { name: /工单复核/ }).click()
  await expect(page.getByRole('heading', { name: '人工复核队列' })).toBeVisible()

  const comment = '压力读数已与设备记录复核。'
  await page.getByLabel('SIM-WO-0001 填写复核意见').fill(comment)
  await page.getByRole('button', { name: '确认', exact: true }).click()

  await expect(page.getByText(new RegExp(`已确认 · ${comment}`))).toBeVisible()
  expect(mocks.reviewRequests).toEqual([{
    ticketId: 'SIM-WO-0001',
    body: { decision: 'ACKNOWLEDGED', comment },
  }])
  await page.getByRole('button', { name: '审计记录' }).click()
  await expect(page.getByRole('heading', { name: '系统审计轨迹' })).toBeVisible()
  await expect(page.getByText('WORK_ORDER_REVIEWED', { exact: true })).toBeVisible()
  await expectNoHorizontalOverflow(page)
})

test('admin can submit an acknowledged work order to the configured EAM adapter', async ({ page }) => {
  const mocks = await installMocks(page, ['admin'])
  await signIn(page)

  await page.getByRole('button', { name: /工单复核/ }).click()
  const order = page.locator('.work-order-row').filter({ hasText: 'SIM-WO-0001' })
  await order.getByLabel('SIM-WO-0001 填写复核意见').fill('已确认，提交外部工单。')
  await order.getByRole('button', { name: '确认', exact: true }).click()
  await expect(order.locator('.eam-status')).toContainText('尚未提交 EAM')

  await order.getByRole('button', { name: '提交 EAM', exact: true }).click()
  await expect(order.locator('.eam-status')).toContainText('EAM 已提交')
  await expect(order.locator('.eam-status')).toContainText('EAM-SIM-WO-0001')
  await expect(order.getByRole('button', { name: '提交 EAM', exact: true })).toHaveCount(0)
  expect(mocks.eamRequests).toEqual(['SIM-WO-0001'])
  await expectNoHorizontalOverflow(page)
})

test('desktop history tables load older mission, work-order, and audit records', async ({ page }) => {
  await installMocks(page, ['admin'], { paginateHistory: true })
  await signIn(page)

  await expect(page.getByRole('table').getByText('RUN-0000000000000051', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'EN', exact: true }).click()
  await page.getByRole('button', { name: 'Load older records', exact: true }).click()
  await expect(page.getByRole('table').getByText('RUN-0000000000000001', { exact: true })).toBeVisible()
  await expect(page.locator('.clickable-row')).toHaveCount(51)

  await page.getByRole('button', { name: '中文', exact: true }).click()
  await page.getByRole('button', { name: /工单复核/ }).click()
  await page.getByRole('button', { name: '加载更早记录', exact: true }).click()
  await expect(page.getByText('SIM-WO-0001', { exact: true })).toBeVisible()
  const oldOrder = page.locator('.work-order-row').filter({ hasText: 'SIM-WO-0001' })
  await oldOrder.getByLabel('SIM-WO-0001 填写复核意见').fill('已复核历史记录。')
  await oldOrder.getByRole('button', { name: '确认', exact: true }).click()
  await expect(oldOrder.locator('.review-state')).toHaveText('已确认')

  await page.getByRole('button', { name: '审计记录' }).click()
  await page.getByRole('button', { name: '加载更早记录', exact: true }).click()
  await expect(page.locator('.audit-row').filter({ hasText: 'RUN-0000000000000001' })).toBeVisible()
  await expect(page.locator('.audit-row')).toHaveCount(52)
})

test('authenticated account without an application role is denied console access', async ({ page }) => {
  await installMocks(page, [])
  await signIn(page)

  await expect(page.getByRole('heading', {
    name: '此账户尚未获得巡检平台访问权限',
  })).toBeVisible()
  await expect(page.getByRole('heading', { name: '站点运行概览' })).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})

test('viewer receives read-only navigation and cannot see privileged controls', async ({ page }) => {
  await installMocks(page, ['viewer'])
  await signIn(page)

  await expect(page.getByRole('heading', { name: '站点运行概览' })).toBeVisible()
  await expect(page.locator('.top-actions').getByRole('button', { name: '创建巡检' })).toHaveCount(0)
  await expect(page.locator('.latest-run-panel').getByRole('button', { name: '创建巡检' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '审计记录', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: /工单复核/ }).click()
  await expect(page.getByRole('heading', { name: '人工复核队列' })).toBeVisible()
  await expect(page.locator('.review-actions')).toHaveCount(0)
  await expect(page.getByLabel('SIM-WO-0001 填写复核意见')).toHaveCount(0)
  await expectNoHorizontalOverflow(page)
})
