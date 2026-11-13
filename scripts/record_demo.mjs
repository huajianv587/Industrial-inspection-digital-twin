import { chromium } from '../web/node_modules/playwright/index.mjs'
import { access, mkdir, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'

const ROOT = path.resolve(decodeURIComponent(new URL('..', import.meta.url).pathname))
const OUTPUT_ROOT = path.join(ROOT, 'outputs', 'demo-video-20261030')
const RAW_ROOT = path.join(OUTPUT_ROOT, 'raw-chrome-recordings')
const BASE_URL = process.env.DEMO_URL || 'http://127.0.0.1:5184'
const API_URL = process.env.DEMO_API_URL || 'http://127.0.0.1:8016'
const RUN_ID = 'RUN-V36-PRECISION-INSPECTION-REALISM'
const VIEWPORT = { width: 1440, height: 900 }
const chapterSpecs = [
  { id: '01-title-and-positioning', seconds: 25 },
  { id: '02-portal-overview', seconds: 45 },
  { id: '03-operations-console', seconds: 45 },
  { id: '04-digital-twin-multiview', seconds: 65 },
  { id: '05-top-down-route-planning', seconds: 65 },
  { id: '06-synchronized-video-replay', seconds: 65 },
  { id: '07-evidence-workbench', seconds: 55 },
  { id: '08-anomaly-review-and-eam', seconds: 70 },
  { id: '09-summary-and-boundary', seconds: 30 },
]
const RECORD_LOCALES = (process.env.DEMO_LOCALES || 'zh,en').split(',').map((value) => value.trim()).filter(Boolean)
const START_CHAPTER = Math.min(chapterSpecs.length, Math.max(1, Number(process.env.DEMO_START_CHAPTER || 1)))
const END_CHAPTER = Math.min(chapterSpecs.length, Math.max(START_CHAPTER, Number(process.env.DEMO_END_CHAPTER || chapterSpecs.length)))

const nowIso = () => new Date().toISOString()
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`${url} returned ${response.status}`)
  return response.json()
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function makeIsolatedOrder() {
  return {
    ticket_id: 'SIM-WO-VID-0001',
    run_id: RUN_ID,
    severity: 'HIGH',
    review_status: 'PENDING',
    payload: {
      device_name: '蒸汽主管道压力表与隔离阀组',
      anomaly_codes: ['PRESSURE_HIGH', 'LEAK_SUSPECTED'],
      recommended_actions: ['疑似压力异常，需人工复核后决定处置。'],
    },
    reviewed_by: null,
    review_decision: null,
    review_comment: null,
    created_at: '2026-10-30T02:17:00+00:00',
    reviewed_at: null,
    eam_submission: null,
  }
}

async function installIsolatedWorkflowMock(page, realDashboard, realMission, realArtifacts) {
  const state = { order: makeIsolatedOrder() }
  const auditEvents = [
    {
      event_id: 'demo-audit-001', actor: 'operator@example.test', actor_role: 'operator',
      event_type: 'MISSION_RESULT_IMPORTED', resource_type: 'mission', resource_id: RUN_ID,
      payload: { source: 'synthetic_simulation' }, created_at: '2026-10-30T02:16:02+00:00',
    },
    {
      event_id: 'demo-audit-002', actor: 'operator@example.test', actor_role: 'operator',
      event_type: 'WORK_ORDER_REVIEWED', resource_type: 'work_order', resource_id: 'SIM-WO-VID-0001',
      payload: { review_decision: 'ACKNOWLEDGED' }, created_at: '2026-10-30T02:18:12+00:00',
    },
    {
      event_id: 'demo-audit-003', actor: 'admin@example.test', actor_role: 'admin',
      event_type: 'EAM_SUBMITTED', resource_type: 'work_order', resource_id: 'SIM-WO-VID-0001',
      payload: { external_id: 'EAM-SIM-WO-VID-0001' }, created_at: '2026-10-30T02:18:24+00:00',
    },
  ]

  const fulfill = async (route, payload, status = 200) => route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(payload),
  })

  await page.route('**/api/v1/dashboard', async (route) => {
    const dashboard = clone(realDashboard)
    dashboard.eam_enabled = true
    dashboard.mission_counts = { SUCCEEDED: 1 }
    dashboard.recent_missions = [clone(realMission)]
    dashboard.pending_work_orders = state.order.review_status === 'PENDING' ? 1 : 0
    await fulfill(route, dashboard)
  })

  await page.route('**/api/v1/missions*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathName = url.pathname.replace(/^\/api\/v1/, '')
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }
    if (pathName === '/missions') {
      await fulfill(route, [clone(realMission)])
      return
    }
    if (pathName === `/missions/${RUN_ID}`) {
      await fulfill(route, clone(realMission))
      return
    }
    if (pathName === `/missions/${RUN_ID}/artifacts`) {
      await fulfill(route, clone(realArtifacts))
      return
    }
    await route.continue()
  })

  await page.route('**/api/v1/work-orders*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathName = url.pathname.replace(/^\/api\/v1/, '')
    if (request.method() === 'GET' && pathName === '/work-orders') {
      await fulfill(route, [state.order])
      return
    }
    const reviewMatch = pathName.match(/^\/work-orders\/([^/]+)\/review$/)
    if (request.method() === 'POST' && reviewMatch) {
      const body = request.postDataJSON() || {}
      state.order = {
        ...state.order,
        review_status: 'REVIEWED',
        reviewed_by: 'operator@example.test',
        review_decision: body.decision || 'ACKNOWLEDGED',
        review_comment: body.comment || 'Verified against synchronized synthetic evidence.',
        reviewed_at: nowIso(),
      }
      await fulfill(route, {
        ticket_id: state.order.ticket_id,
        review_status: state.order.review_status,
        reviewed_by: state.order.reviewed_by,
        reviewed_at: state.order.reviewed_at,
      })
      return
    }
    const eamMatch = pathName.match(/^\/work-orders\/([^/]+)\/eam$/)
    if (request.method() === 'POST' && eamMatch) {
      state.order = {
        ...state.order,
        eam_submission: {
          status: 'SUBMITTED', attempts: 1, external_id: 'EAM-SIM-WO-VID-0001',
          submitted_at: nowIso(), updated_at: nowIso(),
        },
      }
      await fulfill(route, {
        ticket_id: state.order.ticket_id,
        status: 'SUBMITTED',
        external_id: state.order.eam_submission.external_id,
        idempotent_replay: false,
      })
      return
    }
    await route.continue()
  })

  await page.route('**/api/v1/audit-events*', async (route) => {
    if (route.request().method() === 'GET') {
      await fulfill(route, auditEvents)
      return
    }
    await route.continue()
  })
}

async function waitForConsole(page) {
  await page.goto(`${BASE_URL}/console`, { waitUntil: 'domcontentloaded' })
  await page.locator('.app-shell').waitFor({ state: 'visible', timeout: 20_000 })
  await page.waitForTimeout(1600)
}

async function setLocale(page, locale) {
  const buttonText = locale === 'zh' ? '中文' : 'EN'
  const switchButton = page.locator('.language-switch button, .project-language button').filter({ hasText: buttonText }).first()
  if (await switchButton.count()) await switchButton.click()
  await page.waitForTimeout(600)
}

async function openMissionDetail(page) {
  const row = page.locator('.site-waypoint-row').first()
  await row.waitFor({ state: 'visible', timeout: 20_000 })
  await row.click()
  await page.locator('.detail-panel').waitFor({ state: 'visible', timeout: 20_000 })
  await page.waitForTimeout(3500)
}

async function scrollDetailTo(page, selector) {
  const target = page.locator(selector).first()
  await target.waitFor({ state: 'visible', timeout: 20_000 })
  await target.scrollIntoViewIfNeeded()
  await page.waitForTimeout(900)
}

async function holdFor(startedAt, seconds) {
  const remaining = Math.max(0, seconds * 1000 - (Date.now() - startedAt))
  if (remaining > 0) await sleep(remaining)
}

async function runChapter(page, locale, chapterIndex) {
  const startedAt = Date.now()
  const spec = chapterSpecs[chapterIndex]
  const isZh = locale === 'zh'
  const labels = isZh ? {
    console: '进入控制台',
    sitePlanPoint: '.project-plan-point-4',
    simulation: '场景与仿真',
    close: '关闭',
    robotPlayTitle: '播放机器人路线',
    replayPlayTitle: '播放回放',
    replayPauseTitle: '暂停回放',
    robotPauseTitle: '暂停机器人路线',
    openEvidenceTitle: '查看原图',
    workOrders: '工单复核',
    audit: '审计记录',
    confirm: '确认',
    eamSubmit: '提交 EAM',
  } : {
    console: 'Open console',
    sitePlanPoint: '.project-plan-point-4',
    simulation: 'Scene & execution',
    close: 'Close',
    robotPlayTitle: 'Play robot route',
    replayPlayTitle: 'Play replay',
    replayPauseTitle: 'Pause replay',
    robotPauseTitle: 'Pause robot route',
    openEvidenceTitle: 'Open source image',
    workOrders: 'Work orders',
    audit: 'Audit log',
    confirm: 'Acknowledge',
    eamSubmit: 'Submit to EAM',
  }

  if (chapterIndex === 0 || chapterIndex === 1) {
    await page.goto(`${BASE_URL}/overview`, { waitUntil: 'domcontentloaded' })
    await setLocale(page, locale)
    await page.locator('.project-hero').waitFor({ state: 'visible' })
    await page.evaluate(() => window.scrollTo(0, 0))
    if (chapterIndex === 1) {
      await page.locator(labels.sitePlanPoint).click()
      await page.waitForTimeout(800)
      await page.locator('#system').scrollIntoViewIfNeeded()
      await page.waitForTimeout(1200)
      await page.locator('#workflow').scrollIntoViewIfNeeded()
    }
  } else if (chapterIndex === 2) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await page.locator('.summary-strip').waitFor({ state: 'visible' })
    await page.waitForTimeout(1800)
  } else if (chapterIndex === 3) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await openMissionDetail(page)
    await page.locator('.scene-camera-button').nth(1).click()
    await page.waitForTimeout(1200)
    await page.locator('.scene-camera-button').nth(5).click()
    await page.waitForTimeout(1200)
    await page.locator('.scene-viewer-actions .secondary-button').first().click()
    await page.waitForTimeout(1200)
  } else if (chapterIndex === 4) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await openMissionDetail(page)
    await scrollDetailTo(page, '.replay-map-panel')
    await page.locator('.replay-speed-control button').filter({ hasText: '0.5x' }).click()
    await page.locator('.replay-control-buttons .icon-button').first().click()
    await page.locator('.replay-play-button').click()
    await page.waitForTimeout(15_000)
    await page.locator('.replay-play-button').click()
    await page.locator('.replay-timeline-marker').nth(3).click()
  } else if (chapterIndex === 5) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await openMissionDetail(page)
    await scrollDetailTo(page, '.replay-feed-grid')
    await page.locator('.replay-speed-control button').filter({ hasText: '0.25x' }).click()
    await page.locator('.replay-play-button').click()
    await page.waitForTimeout(18_000)
    await page.locator('.replay-play-button').click()
    await page.locator('.replay-control-buttons .icon-button').nth(1).click()
  } else if (chapterIndex === 6) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await openMissionDetail(page)
    await scrollDetailTo(page, '.replay-evidence-panel')
    const replaySelects = page.locator('.replay-workbench-bar select')
    const waypointSelect = replaySelects.nth(0)
    const cameraSelect = replaySelects.nth(1)
    const evidenceSelect = replaySelects.nth(2)
    await waypointSelect.selectOption('WP_04_PUMP')
    await cameraSelect.selectOption('robot')
    await page.waitForTimeout(900)
    await cameraSelect.selectOption('paired')
    await evidenceSelect.selectOption('verified')
    await page.waitForTimeout(1600)
    const openEvidence = page.locator(`button[title="${labels.openEvidenceTitle}"]`).first()
    if (await openEvidence.count()) {
      const popupPromise = page.waitForEvent('popup', { timeout: 2500 }).catch(() => null)
      await openEvidence.click()
      const popup = await popupPromise
      if (popup) await popup.close().catch(() => undefined)
    }
  } else if (chapterIndex === 7) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await page.locator('.main-nav .nav-item').filter({ hasText: labels.workOrders }).click()
    await page.locator('.work-order-row').waitFor({ state: 'visible', timeout: 20_000 })
    await page.waitForTimeout(1100)
    const reviewInput = page.locator('.review-actions input').first()
    await reviewInput.fill(isZh ? '已核对双路合成证据，建议进入维护流程。' : 'Paired synthetic evidence reviewed; proceed to maintenance workflow.')
    await page.getByRole('button', { name: labels.confirm, exact: true }).click()
    await page.waitForTimeout(2200)
    const eamButton = page.getByRole('button', { name: labels.eamSubmit, exact: true })
    if (await eamButton.count()) {
      await eamButton.click()
      await page.waitForTimeout(2400)
    }
    await page.locator('.main-nav .nav-item').filter({ hasText: labels.audit }).click()
    await page.locator('.audit-list').waitFor({ state: 'visible', timeout: 20_000 })
  } else if (chapterIndex === 8) {
    await waitForConsole(page)
    await setLocale(page, locale)
    await openMissionDetail(page)
    await scrollDetailTo(page, '.scene-viewer-footer')
    await page.waitForTimeout(900)
    await scrollDetailTo(page, '.replay-heading')
  }

  await holdFor(startedAt, spec.seconds)
}

async function recordLocale(browser, locale, realDashboard, realMission, realArtifacts) {
  const records = []
  for (let index = START_CHAPTER - 1; index < END_CHAPTER; index += 1) {
    const spec = chapterSpecs[index]
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: 1,
      recordVideo: { dir: RAW_ROOT, size: VIEWPORT },
    })
    const page = await context.newPage()
    const pageErrors = []
    const consoleErrors = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    await installIsolatedWorkflowMock(page, realDashboard, realMission, realArtifacts)
    const startedAt = nowIso()
    let failure = null
    try {
      await runChapter(page, locale, index)
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error)
      console.error(`[record] ${locale}/${spec.id} failed: ${failure}`)
    }
    const video = page.video()
    await context.close()
    const sourcePath = video ? await video.path() : null
    const outputName = `${locale}-${spec.id}.webm`
    const outputPath = path.join(RAW_ROOT, outputName)
    if (sourcePath) await rename(sourcePath, outputPath)
    records.push({
      locale,
      chapter: index + 1,
      id: spec.id,
      seconds_target: spec.seconds,
      recorded_at: startedAt,
      raw_path: outputPath,
      page_errors: pageErrors,
      console_errors: consoleErrors,
      failure,
    })
    console.log(`[record] ${locale} chapter ${index + 1}/${END_CHAPTER}: ${outputName}`)
  }
  return records
}

await mkdir(RAW_ROOT, { recursive: true })
const realDashboard = await fetchJson(`${API_URL}/api/v1/dashboard`)
const realMission = await fetchJson(`${API_URL}/api/v1/missions/${RUN_ID}`)
const realArtifacts = await fetchJson(`${API_URL}/api/v1/missions/${RUN_ID}/artifacts`)
const browser = await chromium.launch({ channel: 'chrome', headless: false })
const startedAt = nowIso()
const records = []
try {
  for (const locale of RECORD_LOCALES) {
    records.push(...await recordLocale(browser, locale, realDashboard, realMission, realArtifacts))
  }
} finally {
  await browser.close()
}

const manifestPath = path.join(OUTPUT_ROOT, 'recording-manifest.json')
const knownRecords = new Map(records.map((record) => [`${record.locale}:${record.chapter}`, record]))
for (const locale of ['zh', 'en']) {
  for (const [index, spec] of chapterSpecs.entries()) {
    const rawPath = path.join(RAW_ROOT, `${locale}-${spec.id}.webm`)
    const key = `${locale}:${index + 1}`
    if (knownRecords.has(key)) continue
    try {
      await access(rawPath)
      knownRecords.set(key, {
        locale,
        chapter: index + 1,
        id: spec.id,
        seconds_target: spec.seconds,
        recorded_at: startedAt,
        raw_path: rawPath,
        page_errors: [],
        console_errors: [],
        failure: null,
      })
    } catch {
      // The chapter has not been recorded yet.
    }
  }
}
const manifest = {
  schema_version: 1,
  generated_at: nowIso(),
  recording_started_at: startedAt,
  base_url: BASE_URL,
  api_url: API_URL,
  browser: 'Chrome channel via Playwright',
  viewport: VIEWPORT,
  run_id: RUN_ID,
  simulation_boundary: 'Local Blender/Three.js synthetic data. No physical robot, field camera, or live EAM action was used.',
  isolated_workflow_mock: true,
  chapters: chapterSpecs,
  recordings: [...knownRecords.values()].sort((left, right) => left.locale.localeCompare(right.locale) || left.chapter - right.chapter),
}
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
console.log(`[record] manifest written: ${manifestPath}`)
