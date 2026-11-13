import { useState, type KeyboardEvent } from 'react'
import {
  ArrowDown, ArrowRight, ArrowUpRight, Bot, Check, ClipboardCheck,
  Database, Factory, MapPin, ScanEye, ShieldCheck,
} from 'lucide-react'
import configuredSite from '../../configs/site.json'
import industrialSite from '../../configs/industrial_site_v12.json'
import './project-home.desktop.css'

type Locale = 'zh' | 'en'

type ProjectHomeProps = {
  locale: Locale
  onLocaleChange: (locale: Locale) => void
}

type SitePlanConfig = {
  site_id: string
  waypoints: Array<{
    waypoint_id: string
    device_id: string
    device_name: string
    zone: string
    position: { x: number; y: number; z?: number }
  }>
}

const localDemoMode = import.meta.env.VITE_LOCAL_DEMO === '1'
const siteConfig: SitePlanConfig = localDemoMode ? industrialSite : configuredSite

const sitePlanProjection = (() => {
  const points = siteConfig.waypoints
  const xs = points.map(({ position }) => position.x)
  const ys = points.map(({ position }) => position.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX
  const spanY = maxY - minY
  const left = 42
  const right = 458
  const top = 42
  const bottom = 228
  const scale = Math.min((right - left) / (spanX || 1), (bottom - top) / (spanY || 1))
  const xOffset = left + ((right - left) - spanX * scale) / 2
  const yOffset = top + ((bottom - top) - spanY * scale) / 2

  return {
    project(x: number, y: number) {
      return {
        x: xOffset + (x - minX) * scale,
        y: yOffset + (maxY - y) * scale,
      }
    },
  }
})()

const sitePlanPoints = (() => {
  return siteConfig.waypoints.map((waypoint, index) => ({
    waypoint,
    index,
    ...sitePlanProjection.project(waypoint.position.x, waypoint.position.y),
  }))
})()

const sitePlanEnglishZones: Record<string, string> = {
  WP_01_PIPE: 'PIPE RACK A',
  WP_02_VESSEL: 'STEAM / SEPARATOR A',
  WP_03_CABINET: 'ELECTRICAL ROOM B',
  WP_04_PUMP: 'PUMP SKID C',
  WP_05_EXCHANGER: 'HEAT EXCHANGE C',
  WP_06_FILTER: 'FILTRATION C',
  WP_07_HVAC: 'NORTH HVAC A',
  WP_08_FIRE: 'FIRE RESPONSE D',
  WP_09_MRO: 'MRO / SPARES E',
  WP_10_CRANE: 'OVERHEAD CRANE A',
}

const collisionSafePlanLegs: Record<string, Array<readonly [number, number]>> = {
  WP_01_PIPE: [[0, 2.05], [6.35, 2.05], [4.0, 2.05]],
  WP_02_VESSEL: [[-0.25, 2.05], [-0.25, 2.9]],
  WP_03_CABINET: [[-0.25, -0.9], [6.0, -0.9], [6.0, -1.5], [8.0, -1.5]],
  WP_04_PUMP: [[9.6, -1.5], [9.6, 2.0], [11.5, 2.0]],
  WP_05_EXCHANGER: [[12.7, 2.0], [12.7, 1.6], [14.6, 1.6]],
  WP_06_FILTER: [[17.0, 1.6], [18.2, 1.6], [18.2, -4.85], [16.7, -4.85]],
  WP_07_HVAC: [[18.2, -4.85], [18.2, 6.6], [4.4, 6.6], [4.4, 4.65], [2.8, 4.65]],
  WP_08_FIRE: [[1.8, 4.65], [1.8, -0.9], [12.7, -0.9], [12.7, -3.85], [15.8, -3.85]],
  WP_09_MRO: [[12.7, -3.85], [12.7, -5.0], [-2.35, -5.0]],
  WP_10_CRANE: [[-3.4, -5.0], [-3.4, -0.9], [6.0, -0.9], [6.0, 3.55]],
}

function appendPlanRoutePoint(points: Array<readonly [number, number]>, point: readonly [number, number]) {
  const previous = points[points.length - 1]
  if (!previous || Math.hypot(previous[0] - point[0], previous[1] - point[1]) > 0.001) points.push(point)
}

function orthogonalPlanPath(points: Array<{ x: number; y: number }>) {
  if (points.length < 2) return ''
  const first = points[0]
  const segments = [`M ${first.x} ${first.y}`]
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index]
    const next = points[index + 1]
    const bendX = (current.x + next.x) / 2
    segments.push(`L ${bendX} ${current.y} L ${bendX} ${next.y} L ${next.x} ${next.y}`)
  }
  return segments.join(' ')
}

const sitePlanRouteWorldPoints = (() => {
  const points: Array<readonly [number, number]> = [[0, 0]]
  siteConfig.waypoints.forEach((waypoint) => {
    const position = waypoint.position
    const configuredLeg = localDemoMode ? collisionSafePlanLegs[waypoint.waypoint_id] : undefined
    if (configuredLeg?.length) {
      configuredLeg.forEach((point) => appendPlanRoutePoint(points, point))
      return
    }
    const previous = points[points.length - 1] || [0, 0]
    const bendX = (previous[0] + position.x) / 2
    appendPlanRoutePoint(points, [bendX, previous[1]])
    appendPlanRoutePoint(points, [bendX, position.y])
    appendPlanRoutePoint(points, [position.x, position.y])
  })
  return points
})()

const sitePlanRoutePoints = sitePlanRouteWorldPoints.map(([x, y]) => sitePlanProjection.project(x, y))
const sitePlanRoutePath = orthogonalPlanPath(sitePlanRoutePoints)
const sitePlanZoneBoxes = (localDemoMode ? [
  { id: 'UTIL-A', x: -3.5, y: 0.15, width: 9.8, height: 6.55 },
  { id: 'ELEC-B', x: 5.9, y: -6.95, width: 3.55, height: 5.55 },
  { id: 'UTIL-B', x: 9.7, y: -6.95, width: 7.65, height: 12.05 },
  { id: 'MRO-C', x: -3.5, y: -7.75, width: 4.7, height: 4.0 },
  { id: 'SAFE-C', x: 17.55, y: -6.95, width: 1.05, height: 12.05 },
] : []).map((zone) => {
  const topLeft = sitePlanProjection.project(zone.x, zone.y + zone.height)
  const bottomRight = sitePlanProjection.project(zone.x + zone.width, zone.y)
  return { ...zone, x: topLeft.x, y: topLeft.y, width: bottomRight.x - topLeft.x, height: bottomRight.y - topLeft.y }
})

function sitePlanZone(waypoint: SitePlanConfig['waypoints'][number], locale: Locale) {
  if (locale === 'en') return sitePlanEnglishZones[waypoint.waypoint_id] || waypoint.zone
  return waypoint.zone.replace(/^模拟/, '')
}

const copy = {
  zh: {
    brand: '工业巡检平台', brandSub: '单站点 · 工业运维系统', technicalMark: '● 单站点工业操作系统',
    navSystem: '系统能力', navFlow: '运行链路', navScope: '交付边界', console: '进入控制台',
    eyebrow: '单站点 / 巡检系统',
    title: '工业巡检平台',
    intro: '围绕任务创建、执行调度、结果校验与人工复核，构建可追溯的单站点运维链路。',
    openConsole: '打开运维控制台', viewFlow: '查看运行链路',
    heroNote: '状态依据本地软件测试与云端 schema 核验整理；仿真与集群执行尚未运行。',
    mainNavigation: '主导航', heroImageAlt: '工程实验室中的设备验证环境', heroCaptionPrimary: '工程验证环境', heroCaptionSecondary: '非现场部署画面', systemStack: '系统技术边界', syntheticOnly: '仅合成数据',
    configuredWaypoints: '配置巡检点位',
    heroFacts: [
      ['4 / 4', '软件基线检查', '配置 · 演示 · 数据 · 评测'],
      ['0', '真实集群作业', '尚未提交 Slurm 作业验证'],
    ],
    stateTitle: '项目核验快照', verificationBadge: '软件基线核验通过 / 仿真模式', mapHudDevice: '设备编号', mapHudCoordinate: '平面坐标', mapHudStatus: '状态', mapHudMode: '配置 / 合成数据',
    sitePlanKicker: '配置坐标', sitePlanMeta: 'XY / 本地坐标 / m', sitePlanRouteBadge: '避障通道 / 缓冲 0.45 m', sitePlanRobot: '仿真机器人',
    sitePlanTitle: '站点配置路线',
    sitePlanCaption: '配置坐标关系示意；不是实时地图或机器人定位。',
    stateRows: [
      ['执行来源', 'OFFLINE', '合成仿真数据源', 'warning'],
      ['云端数据库', 'SUPABASE', '专用项目 schema 已核验', 'ready'],
      ['任务 Worker', 'NOT SEEN', '心跳已实现；尚无运行实例', 'warning'],
      ['仿真运行时', 'NOT VALIDATED', 'Isaac Sim / ROS 2 未运行', 'warning'],
      ['现场系统', 'NOT CONNECTED', '无真机或 EAM 接入', 'neutral'],
    ],
    systemKicker: '平台模块',
    systemTitle: '从运行记录到人工确认',
    systemIntro: '按职责拆分模块，测量来源、数据质量和系统边界随任务保留。',
    areas: [
      { icon: Factory, number: '01', code: 'MOD-01 // OPS', title: '运行指挥', label: '模块 01', status: '实现基线', text: '创建单站点任务，查看执行状态、配置点位、运行历史和结果制品。' },
      { icon: Bot, number: '02', code: 'MOD-02 // TWIN', title: '场景与调度', label: '模块 02', status: '集群未验证', text: '任务清单、Slurm SSH/SCP、worker 心跳与回传校验已实现；尚未提交真实集群作业。' },
      { icon: ScanEye, number: '03', code: 'MOD-03 // PERCEPTION', title: '感知与诊断', label: '模块 03', status: '规则基线', text: '按点位展示观测、质量标记和规则告警；缺失值保留为未知，不默认判正常。' },
      { icon: ClipboardCheck, number: '04', code: 'MOD-04 // EAM', title: '工单与审计', label: '模块 04', status: 'EAM 待厂商验证', text: '告警由授权人员复核并留痕；已确认工单可由管理员提交到可选 EAM 适配器，不触发现场动作。' },
    ],
    flowKicker: '任务生命周期',
    flowTitle: '一条可追溯的巡检链路',
    flowIntro: '从任务配置到复核记录，每一步绑定 run_id 与来源信息。',
    steps: [
      ['01', '创建任务'], ['02', '冻结任务清单'], ['03', '提交执行器'], ['04', '采集点位数据'],
      ['05', '校验结果包'], ['06', '生成规则告警'], ['07', '人工复核'], ['08', '审计与报告'],
    ],
    currentMode: '当前可复现路径',
    currentModeText: '离线适配器 → 合成观测 → 规则诊断 → 人工复核。仿真数据不代表工厂现场表现。',
    scopeKicker: '实现与验证边界', scopeTitle: '当前交付边界',
    scopeItems: [
      ['已实现', 'FastAPI 控制台 API、Supabase schema、任务与工单审计、worker 心跳、Slurm 客户端接口及可选 EAM adapter。'],
      ['待验证', 'Supabase 用户登录与 Storage 文件读写、worker/Compose 实际运行、Slurm 验证作业、EAM 厂商 endpoint。'],
      ['尚未实现', 'Isaac Sim / ROS 2 真实运行、训练模型与独立评测、真机控制和现场安全验收。'],
    ],
    scopeNote: '项目现阶段是可测试的软件基线，不宣称已完成真实机器人或工厂现场部署。',
    footer: '系统状态与能力说明按当前代码实现和验证记录整理。',
    language: '界面语言', chinese: '中文', english: 'EN',
    telemetryKernel: '系统内核 / 在线仿真', telemetrySite: '站点集群', telemetryWaypoints: '激活点位', telemetryClock: '时间基准 / UTC 同步',
  },
  en: {
    brand: 'Industrial Inspection', brandSub: 'SINGLE SITE · OPERATIONS SYSTEM', technicalMark: '● SINGLE-SITE INDUSTRIAL OS',
    navSystem: 'System', navFlow: 'Workflow', navScope: 'Scope', console: 'Open console',
    eyebrow: 'SITE OPERATIONS / INSPECTION SYSTEM',
    title: 'Industrial Inspection Platform',
    intro: 'A traceable, single-site operations workflow for mission creation, execution dispatch, result validation, and human review.',
    openConsole: 'Open operations console', viewFlow: 'View workflow',
    heroNote: 'Status reflects local software tests and cloud schema checks; simulation and cluster execution have not run.',
    mainNavigation: 'Main navigation', heroImageAlt: 'Equipment validation in an engineering laboratory', heroCaptionPrimary: 'ENGINEERING VALIDATION ENVIRONMENT', heroCaptionSecondary: 'NOT A FIELD DEPLOYMENT', systemStack: 'System stack', syntheticOnly: 'SYNTHETIC ONLY',
    configuredWaypoints: 'CONFIGURED WAYPOINTS',
    heroFacts: [
      ['4 / 4', 'SOFTWARE BASELINE CHECKS', 'config · demo · data · evaluation'],
      ['0', 'REAL CLUSTER JOBS', 'No Slurm smoke job submitted'],
    ],
    stateTitle: 'VERIFICATION SNAPSHOT', verificationBadge: 'SOFTWARE BASELINE VERIFIED / SIMULATION MODE', mapHudDevice: 'DEVICE ID', mapHudCoordinate: 'PLAN COORDINATE', mapHudStatus: 'STATUS', mapHudMode: 'CONFIGURED / SYNTHETIC DATA',
    sitePlanKicker: 'Configured coordinates', sitePlanMeta: 'XY / LOCAL FRAME / M', sitePlanRouteBadge: 'COLLISION-SAFE / 0.45 M CLEARANCE', sitePlanRobot: 'SIM ROBOT',
    sitePlanTitle: 'Configured site route',
    sitePlanCaption: 'Configured coordinate sketch; not a live map or robot localization.',
    stateRows: [
      ['Execution source', 'OFFLINE', 'Synthetic simulation source', 'warning'],
      ['Cloud database', 'SUPABASE', 'Dedicated project schema verified', 'ready'],
      ['Mission worker', 'NOT SEEN', 'Heartbeat implemented; no runtime instance', 'warning'],
      ['Simulation runtime', 'NOT VALIDATED', 'Isaac Sim / ROS 2 not run', 'warning'],
      ['Field systems', 'NOT CONNECTED', 'No robot or EAM integration', 'neutral'],
    ],
    systemKicker: 'Platform modules',
    systemTitle: 'From run records to human review',
    systemIntro: 'Modules are separated by responsibility. Source, quality, and system boundaries travel with each run.',
    areas: [
      { icon: Factory, number: '01', code: 'MOD-01 // OPS', title: 'Operations console', label: 'MODULE 01', status: 'Baseline implemented', text: 'Create single-site missions and inspect execution status, configured waypoints, run history, and artifacts.' },
      { icon: Bot, number: '02', code: 'MOD-02 // TWIN', title: 'Scene & scheduling', label: 'MODULE 02', status: 'Cluster not validated', text: 'Manifest, Slurm SSH/SCP, worker heartbeat, and result validation are implemented; no real cluster job has run.' },
      { icon: ScanEye, number: '03', code: 'MOD-03 // PERCEPTION', title: 'Sensing & diagnostics', label: 'MODULE 03', status: 'Rules baseline', text: 'Review waypoint observations, quality flags, and rule findings. Missing measurements remain unknown.' },
      { icon: ClipboardCheck, number: '04', code: 'MOD-04 // EAM', title: 'Work orders & audit', label: 'MODULE 04', status: 'Vendor validation pending', text: 'Authorized people review and record findings. Admins can explicitly submit acknowledged orders to the optional EAM adapter; no field action is triggered.' },
    ],
    flowKicker: 'Mission lifecycle',
    flowTitle: 'One traceable inspection workflow',
    flowIntro: 'Every step from mission setup to review is linked by run_id and provenance.',
    steps: [
      ['01', 'Create mission'], ['02', 'Freeze manifest'], ['03', 'Dispatch executor'], ['04', 'Collect readings'],
      ['05', 'Validate bundle'], ['06', 'Assess findings'], ['07', 'Human review'], ['08', 'Audit & report'],
    ],
    currentMode: 'Reproducible path today',
    currentModeText: 'Offline adapter → synthetic observations → rule assessment → human review. Simulation data is not evidence of field performance.',
    scopeKicker: 'Implementation & validation', scopeTitle: 'Delivery boundary',
    scopeItems: [
      ['Implemented', 'FastAPI operations API, Supabase schema, mission and work-order audit, worker heartbeat, Slurm client interface, and optional EAM adapter.'],
      ['Not validated', 'Supabase user login and Storage I/O, worker/Compose runtime, a Slurm smoke job, and the EAM vendor endpoint.'],
      ['Not implemented', 'Isaac Sim / ROS 2 execution, trained models and independent evaluation, robot control, and field safety acceptance.'],
    ],
    scopeNote: 'This is a testable software baseline, not a claim of deployment on a physical robot or factory floor.',
    footer: 'System status and capability statements reflect the current code and validation record.',
    language: 'Interface language', chinese: '中文', english: 'EN',
    telemetryKernel: 'SYSTEM KERNEL / SIM ONLINE', telemetrySite: 'SITE CLUSTER', telemetryWaypoints: 'ACTIVE WAYPOINTS', telemetryClock: 'TIME REF / UTC SYNC',
  },
} as const

export default function ProjectHome({ locale, onLocaleChange }: ProjectHomeProps) {
  const t = copy[locale]
  const [hoveredWaypoint, setHoveredWaypoint] = useState<number | null>(null)
  const [selectedWaypoint, setSelectedWaypoint] = useState<number | null>(null)
  const activeWaypoint = hoveredWaypoint ?? selectedWaypoint
  const toggleWaypoint = (index: number) => setSelectedWaypoint((current) => current === index ? null : index)
  const handleWaypointKeyDown = (event: KeyboardEvent<SVGGElement>, index: number) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      toggleWaypoint(index)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      setSelectedWaypoint(null)
      setHoveredWaypoint(null)
      return
    }
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown' || event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
      event.preventDefault()
      const delta = (event.key === 'ArrowRight' || event.key === 'ArrowDown') ? 1 : -1
      const nextIndex = (index + delta + sitePlanPoints.length) % sitePlanPoints.length
      const parent = event.currentTarget.parentElement
      const nextNode = parent?.querySelector<SVGGElement>(`.project-plan-point-${nextIndex + 1}`)
      nextNode?.focus()
    }
  }

  return <div className="project-home">
    <header className="project-header">
      <a className="project-brand" href="/overview" aria-label={t.brand}>
        <span className="project-brand-mark"><Factory size={17} strokeWidth={1.8} /></span>
        <span className="project-brand-name"><strong>{t.brand}</strong><small>{t.brandSub}</small></span>
      </a>
      <nav className="project-nav" aria-label={t.mainNavigation}>
        <a href="#system">{t.navSystem}</a>
        <a href="#workflow">{t.navFlow}</a>
        <a href="#scope">{t.navScope}</a>
      </nav>
      <div className="project-header-actions">
        <span className="project-technical-mark"><i />{t.technicalMark}</span>
        <div className="project-language" role="group" aria-label={t.language}>
          <button type="button" aria-pressed={locale === 'zh'} className={locale === 'zh' ? 'selected' : ''} onClick={() => onLocaleChange('zh')}>{t.chinese}</button>
          <button type="button" aria-pressed={locale === 'en'} className={locale === 'en' ? 'selected' : ''} onClick={() => onLocaleChange('en')}>{t.english}</button>
        </div>
        <a className="project-console-link" href="/console">{t.console}<ArrowUpRight size={15} /></a>
      </div>
    </header>

    <main>
      <section className="project-hero" aria-labelledby="project-title">
        <img className="project-hero-image" src="/assets/industrial-workshop-hero.svg" alt={t.heroImageAlt} />
        <div className="project-hero-telemetry" aria-label={locale === 'zh' ? '系统遥测状态' : 'System telemetry'}>
          <span><i className="telemetry-led" />{t.telemetryKernel}</span>
          <span><b>{t.telemetrySite}</b><strong>{siteConfig.site_id}</strong></span>
          <span><b>{t.telemetryWaypoints}</b><strong>{siteConfig.waypoints.length} PTS</strong></span>
          <span><b>{t.telemetryClock}</b><strong>SYNCED</strong></span>
        </div>
        <div className="project-hero-content">
          <div className="project-hero-main">
            <span className="project-hero-verification"><i />{t.verificationBadge}</span>
            <p className="project-eyebrow">{t.eyebrow}</p>
            <h1 id="project-title">{t.title}</h1>
            <p className="project-hero-intro">{t.intro}</p>
            <div className="project-hero-actions">
              <a className="project-cta-primary" href="/console">{t.openConsole}<ArrowRight size={16} /></a>
              <a className="project-cta-secondary" href="#workflow">{t.viewFlow}<ArrowDown size={15} /></a>
            </div>
            <p className="project-hero-note"><ShieldCheck size={14} />{t.heroNote}</p>
          </div>
          <div className="project-hero-tactical">
          <figure className="project-site-plan" aria-labelledby="project-site-plan-title">
            <div className="project-site-plan-heading">
              <div><span>{t.sitePlanKicker} / {siteConfig.site_id}</span><h2 id="project-site-plan-title">{t.sitePlanTitle}</h2></div>
              <div className="project-site-plan-heading-tools"><small className="project-site-plan-meta">{t.sitePlanMeta}</small><MapPin size={15} aria-hidden="true" /></div>
            </div>
            <svg className="project-site-plan-map" viewBox="0 0 500 270" role="group" aria-labelledby="project-map-title project-map-description">
              <title id="project-map-title">{t.sitePlanTitle}</title>
              <desc id="project-map-description">{t.sitePlanCaption}</desc>
              <rect className="project-plan-boundary" x="28" y="32" width="444" height="204" rx="2" />
              <g className="project-plan-zones" aria-hidden="true">
                {sitePlanZoneBoxes.map((zone) => <g key={zone.id}>
                  <rect x={zone.x} y={zone.y} width={zone.width} height={zone.height} rx="1.5" />
                  <text x={zone.x + 6} y={zone.y + 13}>{zone.id}</text>
                </g>)}
              </g>
              {activeWaypoint !== null && sitePlanPoints[activeWaypoint] && (
                <g className="project-plan-crosshairs" aria-hidden="true">
                  <line x1="28" y1={sitePlanPoints[activeWaypoint].y} x2="472" y2={sitePlanPoints[activeWaypoint].y} />
                  <line x1={sitePlanPoints[activeWaypoint].x} y1="32" x2={sitePlanPoints[activeWaypoint].x} y2="236" />
                </g>
              )}
              <g className="project-plan-compass" aria-hidden="true" transform="translate(445 49)">
                <circle cx="0" cy="0" r="13" />
                <path d="M 0 -8 L 4 5 L 0 2 L -4 5 Z" />
                <text x="0" y="-16">N</text>
              </g>
              <g className="project-plan-scale" aria-hidden="true" transform="translate(38 246)">
                <path d="M 0 0 H 48 M 0 -4 V 4 M 48 -4 V 4" />
                <text x="0" y="16">0</text>
                <text x="48" y="16">10 m</text>
              </g>
              <path className="project-plan-route-clearance" d={sitePlanRoutePath} />
              <path className="project-plan-route-glow" d={sitePlanRoutePath} />
              <path className="project-plan-route" d={sitePlanRoutePath} />
              {sitePlanRoutePoints[0] && <g className="project-plan-robot-marker" aria-label={t.sitePlanRobot} transform={`translate(${sitePlanRoutePoints[0].x} ${sitePlanRoutePoints[0].y})`}>
                <circle r="8" /><path d="M 5 0 L -3 -4 L -3 4 Z" />
                <text x="11" y="4">RBT / SIM</text>
              </g>}
              {sitePlanPoints.map(({ waypoint, index, x, y }) => {
                const zone = sitePlanZone(waypoint, locale)
                const coordinateLabel = `X ${waypoint.position.x.toFixed(1)} / Y ${waypoint.position.y.toFixed(1)} m`
                return <g
                  className={`project-plan-point project-plan-point-${index + 1}${activeWaypoint === index ? ' is-active' : ''}`}
                  key={waypoint.waypoint_id}
                  transform={`translate(${x} ${y})`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selectedWaypoint === index}
                  aria-label={`${String(index + 1).padStart(2, '0')} ${zone}, ${coordinateLabel}`}
                  onPointerEnter={() => setHoveredWaypoint(index)}
                  onPointerLeave={() => setHoveredWaypoint(null)}
                  onFocus={() => setHoveredWaypoint(index)}
                  onBlur={() => setHoveredWaypoint(null)}
                  onClick={() => toggleWaypoint(index)}
                  onKeyDown={(event) => handleWaypointKeyDown(event, index)}
                >
                  <circle className="project-plan-sonar project-plan-sonar-a" r="16" /><circle className="project-plan-halo" r="11" /><circle className="project-plan-core" r="7" /><text y="3">{String(index + 1).padStart(2, '0')}</text>
                </g>
              })}
              {activeWaypoint !== null && <g className="project-plan-hud" transform={`translate(${Math.min(sitePlanPoints[activeWaypoint].x + 14, 336)} ${Math.max(sitePlanPoints[activeWaypoint].y - 44, 32)})`}>
                <rect width="148" height="62" rx="3" />
                <path d="M 0 14 H 7 M 0 14 V 7" />
                <text className="project-plan-hud-kicker" x="11" y="14">{sitePlanPoints[activeWaypoint].waypoint.waypoint_id}</text>
                <text x="11" y="29">{t.mapHudDevice}: {sitePlanPoints[activeWaypoint].waypoint.device_id}</text>
                <text x="11" y="43">{t.mapHudCoordinate}: X {sitePlanPoints[activeWaypoint].waypoint.position.x.toFixed(1)} / Y {sitePlanPoints[activeWaypoint].waypoint.position.y.toFixed(1)} m</text>
                <text className="project-plan-hud-status" x="11" y="56">{t.mapHudStatus}: {t.mapHudMode}</text>
              </g>}
              <text className="project-plan-axis" x="454" y="254">X / m</text>
              <text className="project-plan-axis" x="14" y="27">Y / m</text>
            </svg>
            <div className="project-site-plan-status"><span><i />{t.sitePlanRouteBadge}</span><small>{t.sitePlanMeta}</small></div>
            <div className="project-site-plan-legend">
              {sitePlanPoints.map(({ waypoint, index }) => <button
                className="project-site-plan-stop"
                key={waypoint.waypoint_id}
                type="button"
                aria-pressed={selectedWaypoint === index}
                onPointerEnter={() => setHoveredWaypoint(index)}
                onPointerLeave={() => setHoveredWaypoint(null)}
                onFocus={() => setHoveredWaypoint(index)}
                onBlur={() => setHoveredWaypoint(null)}
                onClick={() => setSelectedWaypoint((current) => current === index ? null : index)}
              >
                <i>{String(index + 1).padStart(2, '0')}</i><span>{sitePlanZone(waypoint, locale)}</span>
                <small>X {waypoint.position.x.toFixed(1)} / Y {waypoint.position.y.toFixed(1)} m</small>
              </button>)}
            </div>
            <figcaption>{t.sitePlanCaption}</figcaption>
          </figure>
          <aside className="project-state-rail" aria-label={t.stateTitle}>
            <h2>{t.stateTitle}</h2>
            {t.stateRows.map(([label, value, detail, tone]) => <div className="project-state-row" key={label}>
              <span className="project-state-label">{label}</span>
              <strong className={`state-${tone}`}>{value}</strong>
              <small>{detail}</small>
            </div>)}
          </aside>
          </div>
        </div>
        <div className="project-hero-caption"><span>{t.heroCaptionPrimary}</span><span>{t.heroCaptionSecondary}</span></div>
      </section>

      <section className="project-facts" aria-label={t.systemStack}>
        <div className="project-fact">
          <strong>{siteConfig.waypoints.length}</strong><span className="project-fact-label">{t.configuredWaypoints}</span><small>{siteConfig.site_id}</small>
        </div>
        {t.heroFacts.map(([value, label, detail]) => <div className="project-fact" key={label}>
          <strong>{value}</strong><span className="project-fact-label">{label}</span><small>{detail}</small>
        </div>)}
      </section>

      <section className="project-section project-systems" id="system">
        <div className="project-section-heading">
          <div><span className="project-eyebrow">{t.systemKicker}</span><h2>{t.systemTitle}</h2></div>
          <p>{t.systemIntro}</p>
        </div>
        <div className="project-capabilities">
          {t.areas.map(({ icon: Icon, number, code, title, label, status, text }) => <article className="project-capability" key={number}>
            <span className="project-capability-number">{number}</span>
            <span className="project-capability-icon"><Icon size={18} strokeWidth={1.6} /></span>
            <div className="project-capability-copy"><span className="project-capability-code">{code}</span><span className="project-eyebrow">{label}</span><h3>{title}</h3><p>{text}</p></div>
            <span className="project-capability-status"><i />{status}</span>
          </article>)}
        </div>
      </section>

      <section className="project-workflow" id="workflow">
        <div className="project-section-heading">
          <div><span className="project-eyebrow">{t.flowKicker}</span><h2>{t.flowTitle}</h2></div>
          <p>{t.flowIntro}</p>
        </div>
        <div className="project-flow-bus">
        <span className="project-flow-bus-line" aria-hidden="true" />
        <ol className="project-flow-list">
          {t.steps.map(([number, label], index) => <li key={number}>
            <span className="project-flow-number">{number}</span><strong>{label}</strong>
            {index < t.steps.length - 1 && <ArrowRight className="project-flow-arrow" size={14} />}
          </li>)}
        </ol>
        </div>
        <div className="project-current-mode">
          <span className="project-mode-icon"><Database size={17} /></span>
          <div><strong>{t.currentMode}</strong><p>{t.currentModeText}</p></div>
          <span className="project-mode-label"><i />{t.syntheticOnly}</span>
        </div>
      </section>

      <section className="project-scope" id="scope">
        <div className="project-scope-heading"><span className="project-eyebrow">{t.scopeKicker}</span><h2>{t.scopeTitle}</h2></div>
        <div className="project-scope-list">
          {t.scopeItems.map(([label, text], index) => <div className="project-scope-row" key={label}>
            <span className={`project-scope-index scope-${index}`}>{String(index + 1).padStart(2, '0')}</span><strong>{label}</strong><p>{text}</p>
          </div>)}
        </div>
        <p className="project-scope-note"><Check size={14} />{t.scopeNote}</p>
      </section>
    </main>

    <footer className="project-footer"><span>{t.footer}</span><a href="/console">{t.console}<ArrowUpRight size={14} /></a></footer>
  </div>
}
