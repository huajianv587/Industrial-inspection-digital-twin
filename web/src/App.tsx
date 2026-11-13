import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js'
import type * as THREE from 'three'
import ProjectHome from './ProjectHome'
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, BadgeCheck, Box, Camera, Check, Factory,
  ClipboardCheck, Clock3, ExternalLink, Eye, EyeOff, FileSearch, Hash, Layers3, LogOut,
  MapPin, Plus, RefreshCw, Search, Pause, Play, Rotate3d, Route, ShieldAlert, ShieldCheck,
  SkipBack, SkipForward, SlidersHorizontal, Video, X,
} from 'lucide-react'

const localDemoMode = import.meta.env.VITE_LOCAL_DEMO === '1'
const localDemoVersion = Number(import.meta.env.VITE_LOCAL_DEMO_VERSION || 0)
const isAuditableLocalDemo = localDemoMode && localDemoVersion >= 33
const isV34LocalDemo = localDemoMode && localDemoVersion >= 34
const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || import.meta.env.SUPABASE_URL) as string | undefined
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || import.meta.env.SUPABASE_ANON_KEY) as string | undefined
const supabase: SupabaseClient | null = !localDemoMode && supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey)
  : null
const localDemoSession = {
  access_token: 'local-demo-token',
  token_type: 'bearer',
  expires_in: 86400,
  expires_at: Math.floor(Date.now() / 1000) + 86400,
  refresh_token: 'local-demo-refresh-token',
  user: {
    id: 'local-demo-user',
    aud: 'authenticated',
    role: 'authenticated',
    email: 'local-demo@localhost',
    app_metadata: { provider: 'local', providers: ['local'], roles: ['admin', 'operator', 'reviewer', 'viewer'] },
    user_metadata: {},
    identities: [],
    created_at: new Date(0).toISOString(),
    updated_at: new Date().toISOString(),
  },
} as unknown as Session
const apiBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api/v1'

type Mission = {
  run_id: string; site_id: string; robot_id: string; execution_backend: string
  status: string; seed: number; slurm_job_id: string | null; error: string | null
  created_at: string; updated_at: string; finished_at: string | null
}
type EamSubmission = {
  status: 'PENDING' | 'SUBMITTED' | 'FAILED'
  attempts: number
  external_id: string | null
  submitted_at: string | null
  updated_at: string
}
type WorkOrder = {
  ticket_id: string; run_id: string; severity: string; review_status: string
  payload: Record<string, unknown>; reviewed_by: string | null
  review_decision: string | null; review_comment: string | null
  created_at: string; reviewed_at: string | null; eam_submission: EamSubmission | null
}
type AuditEvent = {
  event_id: string; actor: string; actor_role: string; event_type: string
  resource_type: string; resource_id: string; payload: Record<string, unknown>; created_at: string
}
type Observation = {
  sample_id: string; timestamp_utc: string; source: string; robot_id: string
  waypoint_id: string; device_id: string; pressure_mpa: number | null
  temperature_c: number | null; ambient_temperature_c: number | null
  cabinet_door_closed: boolean | null; leak_detected: boolean | null
  sensor_confidence: Record<string, number>; domain: Record<string, unknown>
}
type Anomaly = { code: string; severity: string; message: string; evidence: Record<string, unknown> }
type WaypointResult = {
  waypoint_id: string; device_id: string; navigation_status: string
  inspection_status: string; observation: Observation | null
  assessment: { severity: string; anomalies: Anomaly[]; data_quality: string; source: string } | null
  work_order: Record<string, unknown> | null; error: string | null
}
type InspectionResult = {
  run_id: string; site_id: string; robot_id: string; started_at_utc: string
  finished_at_utc: string; status: string; source: string; results: WaypointResult[]
}
type MissionDetail = Mission & {
  manifest?: {
    source?: string; software_version?: string; config_sha256?: string
    demo_scenario?: string
    render_backend?: string
    virtual_world?: { engine?: string; render_backend?: string }
    site_config?: { waypoints?: Array<{ waypoint_id: string; device_id: string; device_name: string; zone: string; position?: { x: number; y: number; z?: number }; yaw_deg?: number }> }
  }
  result?: InspectionResult | null
}
type Artifact = {
  artifact_id: string; run_id: string; name: string; sha256: string
  size_bytes: number; source: string; created_at: string
}
type VirtualPose = { x: number; y: number; z?: number; yaw_deg?: number }
type VirtualWaypoint = VirtualPose & {
  waypoint_id: string; device_id: string; device_name: string; zone: string
  asset_id?: string
}
type VirtualSceneInput = {
  waypoints?: VirtualWaypoint[]
  trajectory?: VirtualPose[]
}
type SynchronizedStreamFrame = {
  sequence_index: number
  trajectory_index: number
  render_frame: number
  robot_artifact: string
  cctv_artifact: string
  same_route_frame: boolean
}
type SynchronizedVideoManifest = {
  schema_version: number
  stream_type: string
  frame_count: number
  route_frame_count: number
  frame_duration_s: number
  recommended_playback_speed?: number
  resolution?: { width: number; height: number }
  presentation_resolution?: { width: number; height: number }
  presentation_fps?: number
  presentation_profile?: string
  continuous_manifest?: string
  video_streams?: {
    robot?: ContinuousVideoStream
    cctv?: ContinuousVideoStream
  }
  frames: SynchronizedStreamFrame[]
}
type ContinuousVideoStream = {
  artifact: string
  media_type?: string
  source?: string
  codec?: string
  fps?: number
  duration_s?: number
  width?: number
  height?: number
  frame_count?: number | string
  source_frame_count?: number
  source_frame_duration_s?: number
  presentation_upscaled?: boolean
}
type ReplayCameraMode = 'paired' | 'robot' | 'cctv'
type ReplayEvidenceFilter = 'all' | 'verified' | 'attention'
type SceneSyncState = {
  timecode: string
  frameIndex: number
  routeFrame: number
  renderFrame: number
  streamFrameIndex: number | null
  streamFrameCount: number | null
  playing: boolean
  waypointId: string | null
  deviceName: string | null
  pose: VirtualPose
}
type InspectionSyncCommand = {
  type: 'toggle' | 'play' | 'pause' | 'reset' | 'next' | 'seek'
  frameIndex?: number
}

type RealtimeCameraFeedProps = {
  primaryUrl?: string
  nextUrl?: string
  alt: string
  cameraKind: 'robot' | 'cctv'
  locale: Locale
  playing: boolean
  transitionMs: number
  frameLabel: string
  sourceLabel: string
}
type ContinuousVideoFeedProps = {
  src?: string
  posterUrl?: string
  videoRef: RefObject<HTMLVideoElement | null>
  alt: string
  cameraKind: 'robot' | 'cctv'
  locale: Locale
  playing: boolean
  playbackRate: number
  fpsHint?: number
  frameLabel: string
  sourceLabel: string
  onFrame?: (seconds: number) => void
  onEnded?: () => void
  onReady?: () => void
}
type Site = {
  site_id: string; site_name: string; robot: { robot_id: string; model: string }
  waypoints: Array<{
    waypoint_id: string; asset_id?: string; device_id: string; device_name: string; zone: string
    position?: { x: number; y: number; z?: number }
  }>
}
type IndustrialAsset = {
  asset_id: string; asset_type: string; display_name: string; zone_id: string
  model_asset: string; model_status: 'procedural_proxy' | 'cad_pending' | 'field_verified'
  inspection_points: Array<{ point_id: string; measurement: string; required: boolean }>
}
type IndustrialSite = Site & {
  industrial_profile: {
    plant_type: string; coordinate_system: string; unit_system: string
    model_revision: string; operating_mode: string
  }
  zones: Array<{ zone_id: string; name: string; access: string }>
  assets: IndustrialAsset[]
  sensor_contracts: Array<{
    sensor_id: string; channel: string; unit: string; source_status: string; calibration: string
  }>
  safety: {
    restricted_zones: string[]; stop_conditions: string[]
    human_review_required: string[]; no_automatic_actuation: boolean
  }
}
type IndustrialReadiness = {
  status: 'FIELD_READY' | 'SIMULATION_READY_FIELD_DATA_PENDING'
  asset_count: number; waypoint_count: number; sensor_contract_count: number
  model_status_counts: Record<string, number>; sensor_source_counts: Record<string, number>
  field_deployment_blockers: string[]
}
type IndustrialSiteResponse = { site: IndustrialSite; readiness: IndustrialReadiness }
type Dashboard = {
  site: { site_id: string; site_name: string }; robot: { robot_id: string; model: string }
  execution_backend: string; eam_enabled: boolean; mission_counts: Record<string, number>
  pending_work_orders: number; recent_missions: Mission[]
  worker: {
    status: string; last_seen_at: string | null; execution_backend: string | null
    instance_id: string | null; last_error_type: string | null
  }
}
type HistoryPage<T> = { items: T[]; nextCursor: string | null }
type HistoryCollection = 'missions' | 'workOrders' | 'auditEvents'
type HistoryCursors = Record<HistoryCollection, string | null>
type HistoryLoading = Record<HistoryCollection, boolean>
type Section = 'missions' | 'simulation' | 'diagnostics' | 'work-orders' | 'audit'
type MissionFilter = 'all' | 'active' | 'attention' | 'completed'
type Locale = 'zh' | 'en'
type ApplicationRole = 'admin' | 'operator' | 'reviewer' | 'viewer'
type PendingMissionKeys = Record<string, string>

const pendingMissionStorageKey = 'inspection.pending-mission-keys.v1'
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const applicationRoles = new Set<ApplicationRole>(['admin', 'operator', 'reviewer', 'viewer'])
const consoleSections: readonly Section[] = ['missions', 'simulation', 'diagnostics', 'work-orders', 'audit']

function sectionFromLocation(): Section {
  if (typeof window === 'undefined') return 'missions'
  const view = new URLSearchParams(window.location.search).get('view')
  return view && consoleSections.includes(view as Section) ? view as Section : 'missions'
}

// This controls affordances only; the API remains the authorization boundary.
function rolesFromSession(session: Session | null): Set<ApplicationRole> {
  const roles: unknown = session?.user.app_metadata?.roles
  if (!Array.isArray(roles)) return new Set()
  return new Set(roles.filter((role): role is ApplicationRole =>
    typeof role === 'string' && applicationRoles.has(role as ApplicationRole)))
}

function readPendingMissionKeys(): PendingMissionKeys {
  try {
    const stored = sessionStorage.getItem(pendingMissionStorageKey)
    if (!stored) return {}
    const parsed: unknown = JSON.parse(stored)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(Object.entries(parsed).filter(([fingerprint, key]) =>
      fingerprint.length <= 20_000 && typeof key === 'string' && uuidPattern.test(key)))
  } catch {
    return {}
  }
}

function writePendingMissionKeys(keys: PendingMissionKeys) {
  try {
    if (Object.keys(keys).length) {
      sessionStorage.setItem(pendingMissionStorageKey, JSON.stringify(keys))
    } else {
      sessionStorage.removeItem(pendingMissionStorageKey)
    }
  } catch {
    // In-memory retries remain protected when browser storage is unavailable.
  }
}

function layoutWaypoints(waypoints: Site['waypoints']) {
  const positioned = waypoints.map((waypoint, index) => ({ waypoint, index })).filter(({ waypoint }) => waypoint.position
    && Number.isFinite(waypoint.position.x) && Number.isFinite(waypoint.position.y))
  if (!positioned.length) return []
  const xs = positioned.map(({ waypoint }) => waypoint.position!.x)
  const ys = positioned.map(({ waypoint }) => waypoint.position!.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  return positioned.map(({ waypoint, index }) => ({
    waypoint,
    index,
    x: 56 + ((waypoint.position!.x - minX) / spanX) * 528,
    y: 38 + ((maxY - waypoint.position!.y) / spanY) * 194,
  }))
}

function placeWaypointMapLabels(
  points: Array<readonly [number, number]>,
  occupiedBoxes: Array<{ left: number; top: number; right: number; bottom: number }> = [],
) {
  const width = 38
  const height = 13
  const markerRadius = 13
  const candidates = [
    { dx: 21, dy: 4, anchor: 'start' as const },
    { dx: -21, dy: 4, anchor: 'end' as const },
    { dx: 0, dy: -19, anchor: 'middle' as const },
    { dx: 0, dy: 29, anchor: 'middle' as const },
    { dx: 21, dy: -15, anchor: 'start' as const },
    { dx: -21, dy: -15, anchor: 'end' as const },
    { dx: 21, dy: 23, anchor: 'start' as const },
    { dx: -21, dy: 23, anchor: 'end' as const },
  ]
  const placed: Array<{
    index: number
    x: number
    y: number
    anchor: 'start' | 'middle' | 'end'
    box: { left: number; top: number; right: number; bottom: number }
    leader: { x1: number; y1: number; x2: number; y2: number }
  }> = []
  const density = points.map((point, index) => ({
    index,
    nearest: Math.min(...points.flatMap((other, otherIndex) => otherIndex === index
      ? []
      : [Math.hypot(point[0] - other[0], point[1] - other[1])])),
  })).sort((left, right) => left.nearest - right.nearest)

  density.forEach(({ index }) => {
    const [pointX, pointY] = points[index]
    const ranked = candidates.map((candidate, preference) => {
      const x = pointX + candidate.dx
      const y = pointY + candidate.dy
      const left = candidate.anchor === 'start' ? x : candidate.anchor === 'end' ? x - width : x - width / 2
      const box = { left, top: y - height + 2, right: left + width, bottom: y + 2 }
      const overlapArea = (other: typeof box) => Math.max(0, Math.min(box.right, other.right) - Math.max(box.left, other.left))
        * Math.max(0, Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top))
      const markerOverlap = points.reduce((total, [markerX, markerY], markerIndex) => {
        if (markerIndex === index) return total
        return total + overlapArea({
          left: markerX - markerRadius,
          top: markerY - markerRadius,
          right: markerX + markerRadius,
          bottom: markerY + markerRadius,
        })
      }, 0)
      const occupiedOverlap = occupiedBoxes.reduce((total, box) => total + overlapArea(box), 0)
      const labelOverlap = placed.reduce((total, item) => total + overlapArea(item.box), 0)
      const overflow = Math.max(0, 8 - box.left) + Math.max(0, box.right - 632)
        + Math.max(0, 8 - box.top) + Math.max(0, box.bottom - 292)
      return {
        index, x, y, anchor: candidate.anchor, box,
        leader: (() => {
          const targetX = Math.max(box.left, Math.min(pointX, box.right))
          const targetY = Math.max(box.top, Math.min(pointY, box.bottom))
          const vectorX = targetX - pointX
          const vectorY = targetY - pointY
          const distance = Math.hypot(vectorX, vectorY) || 1
          const inset = Math.min(markerRadius + 2, distance * .45)
          return {
            x1: pointX + (vectorX / distance) * inset,
            y1: pointY + (vectorY / distance) * inset,
            x2: targetX,
            y2: targetY,
          }
        })(),
        score: markerOverlap * 16 + occupiedOverlap * 12 + labelOverlap * 12 + overflow * 80 + preference * 0.01,
      }
    }).sort((left, right) => left.score - right.score)
    placed.push(ranked[0])
  })

  return points.map((_, index) => {
    const { x, y, anchor, leader } = placed.find((item) => item.index === index)!
    return { x, y, anchor, leader }
  })
}

type RouteWaypointInput = {
  waypoint_id: string
  x?: number
  y?: number
  z?: number
  yaw_deg?: number
  position?: { x: number; y: number; z?: number }
}

type PlannedRoute = {
  trajectory: VirtualPose[]
  polyline: VirtualPose[]
  inspectionTargets: VirtualPose[]
  routeDistance: number
  segmentCount: number
}

// These legs follow the plant's service aisles and stop at a safe standoff point
// beside each asset. The asset marker remains at the configured inspection coordinate.
const collisionSafeRouteLegs: Record<string, Array<readonly [number, number]>> = {
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

function routeWaypointPosition(waypoint: RouteWaypointInput) {
  const x = typeof waypoint.x === 'number' ? waypoint.x : waypoint.position?.x
  const y = typeof waypoint.y === 'number' ? waypoint.y : waypoint.position?.y
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  return { x: x as number, y: y as number, z: waypoint.z ?? waypoint.position?.z ?? 0, yaw_deg: waypoint.yaw_deg ?? 0 }
}

function appendRoutePoint(points: Array<readonly [number, number]>, point: readonly [number, number]) {
  const previous = points[points.length - 1]
  if (!previous || Math.hypot(previous[0] - point[0], previous[1] - point[1]) > 0.001) points.push(point)
}

function sampleRoutePolyline(points: Array<readonly [number, number]>, count: number): VirtualPose[] {
  const compact: Array<readonly [number, number]> = []
  points.forEach((point) => appendRoutePoint(compact, point))
  if (compact.length < 2) return [{ x: compact[0]?.[0] || 0, y: compact[0]?.[1] || 0, z: 0, yaw_deg: 0 }]
  const cumulative = [0]
  for (let index = 1; index < compact.length; index += 1) {
    cumulative.push(cumulative[index - 1] + Math.hypot(compact[index][0] - compact[index - 1][0], compact[index][1] - compact[index - 1][1]))
  }
  const total = cumulative[cumulative.length - 1]
  const sampleCount = Math.max(2, count)
  return Array.from({ length: sampleCount }, (_, index) => {
    const distance = total * index / (sampleCount - 1)
    let segment = cumulative.findIndex((value) => value >= distance)
    if (segment < 1) segment = 1
    if (segment >= compact.length) segment = compact.length - 1
    const start = compact[segment - 1]
    const end = compact[segment]
    const segmentLength = cumulative[segment] - cumulative[segment - 1] || 1
    const ratio = Math.max(0, Math.min(1, (distance - cumulative[segment - 1]) / segmentLength))
    const yaw_deg = Math.atan2(end[1] - start[1], end[0] - start[0]) * 180 / Math.PI
    return {
      x: start[0] + (end[0] - start[0]) * ratio,
      y: start[1] + (end[1] - start[1]) * ratio,
      z: 0,
      yaw_deg,
    }
  })
}

function buildCollisionSafeRoute(waypoints: RouteWaypointInput[], frameCount = 214): PlannedRoute {
  const points: Array<readonly [number, number]> = [[0, 0]]
  const inspectionTargets: VirtualPose[] = []
  waypoints.forEach((waypoint) => {
    const position = routeWaypointPosition(waypoint)
    if (!position) return
    const configuredLeg = collisionSafeRouteLegs[waypoint.waypoint_id]
    const leg = configuredLeg?.length ? configuredLeg : [[position.x, position.y] as const]
    leg.forEach((point) => appendRoutePoint(points, point))
    const target = leg[leg.length - 1]
    inspectionTargets.push({ x: target[0], y: target[1], z: position.z, yaw_deg: position.yaw_deg })
  })
  const trajectory = sampleRoutePolyline(points, frameCount)
  const polyline = points.map(([x, y]) => ({ x, y, z: 0, yaw_deg: 0 }))
  const routeDistance = points.slice(1).reduce((total, point, index) => total + Math.hypot(point[0] - points[index][0], point[1] - points[index][1]), 0)
  return { trajectory, polyline, inspectionTargets, routeDistance, segmentCount: Math.max(0, points.length - 1) }
}

const messages = {
  zh: {
    pageTitle: '巡检运营控制台', booting: '正在连接身份服务', brand: '巡检运营平台', brandContext: '现场运维',
    loginTitle: '登录巡检控制台', loginCopy: '查看站点运行状态、创建巡检任务并复核回传结果。', email: '邮箱',
    password: '密码', signIn: '登录', signInProgress: '正在验证…', authRequestFailed: '登录服务暂时不可用，请稍后重试。', authConfigMissing: '尚未配置 Supabase Auth。请提供 VITE_SUPABASE_URL 与 VITE_SUPABASE_ANON_KEY。',
    accountPolicy: '账户权限由身份服务与 API 角色共同校验',
    simulationOnly: '仿真数据，非现场测量',
    simulationPreview: '仿真工作流',
    loginOpsTitle: '工业运行指挥中心', loginOpsCopy: '任务状态、执行记录与待人工复核告警。',
    loginSceneTitle: '场景与执行调度', loginSceneCopy: '核对配置点位与离线或 Slurm 执行记录。',
    loginDiagnosisTitle: '感知与故障诊断', loginDiagnosisCopy: '查看回传测量、质量标记与规则告警；缺失值保持未知。',
    loginReviewTitle: '工单复核与审计', loginReviewCopy: '复核在本系统留痕；已确认工单可由管理员提交到可选 EAM 适配器。',
    mapCaption: '点位坐标来自站点配置，不代表实时地图或机器人定位。', mapLegend: '配置巡检顺序',
    sitePoints: '配置点位', latestRun: '最近一次任务', latestReadings: '点位观测摘要',
    noRunYet: '尚无巡检任务', noReadingsYet: '本次任务尚未回传点位观测。',
    observedPoints: '已回传观测', reportedFindings: '规则告警', configuredRobot: '执行器配置',
    openLatestRun: '打开最近任务详情', pointPosition: '配置坐标',
    mapUnavailable: '站点配置中没有可绘制的点位坐标。',
    scenePageCopy: '查看站点配置点位、巡检顺序与最近一次执行。此视图不是 Isaac Sim 实时画面或机器人定位。',
    industrialRegistryTitle: '工业资产台账与现场就绪状态',
    industrialRegistryCopy: '资产、模型来源、传感器契约和安全门禁均来自工业站点配置；当前数据仍是本地仿真。',
    readinessStatus: '就绪状态', assetRegister: '资产台账', modelSource: '模型来源',
    inspectionPoints: '巡检点', sensorContracts: '传感器契约', sensorSource: '数据来源',
    safetyGate: '安全门禁', fieldBlockers: '现场部署阻断项', fieldDataPending: '现场数据待接入',
    fieldVerified: '现场已验证', proceduralProxy: '程序化代理', cadPending: 'CAD 待补齐',
    sensorSynthetic: '合成仿真', sensorNotConnected: '未接入', restrictedZone: '受限区域',
    stopConditions: '自动停机条件', humanReview: '人工复核条件', noAutomaticActuation: '禁止自动执行设备动作',
    assetCount: '资产数', sensorCount: '传感器数', zoneName: '区域', modelRevision: '模型版本',
    diagnosticsPageCopy: '按点位检查原始观测、数据质量与规则告警；未回传的测量保持未知。',
    diagnosticReadings: '点位诊断', diagnosticMissingRun: '最近任务尚未返回诊断结果。',
    diagnosticNotRun: '暂无可用的巡检观测。创建任务并等待结果回传后，这里会显示点位证据。',
    diagnosticSourceNote: '规则评估与仿真观测；不代表现场测量或模型精度。',
    findingsCount: '告警数', assessment: '评估', waypointDevice: '巡检设备',
    workflowHeadline: '站点运行控制台', workflowCopy: '从任务提交、结果校验到告警复核，查看单站点运行链路。',
    currentSite: '当前站点', loading: '加载中', missions: '运行指挥', simulationSection: '场景与执行', diagnosticsSection: '感知诊断', workOrders: '工单复核',
    navOperations: '01 / 工业运行', navSimulation: '02 / 数字孪生与仿真', navPerception: '03 / 智能感知', navCloseout: '04 / EAM 运维闭环', eamDisconnected: 'EAM 未接入', eamEnabled: 'EAM 适配器已启用 · 厂商待验证',
    controlDesk: '站点控制台', currentClock: '当前时间', executionMode: '执行模式', eamAdapter: 'EAM 适配器', workerHeartbeat: 'Worker 心跳', databaseStatus: '数据库状态', connected: '已连接', simulated: '离线仿真', heartbeatNominal: '心跳正常', renderBackend: '渲染后端', framesPerSecond: '帧率', packetLoss: '丢包率', cameraCode: '机位代号', timecode: '时间码', cabinetStatus: '现场机柜状态',
    slurmJob: 'SLURM 作业号', slurmJobLabel: 'Slurm 作业', seedShort: '种子',
    audit: '审计记录', apiAuthenticated: '登录会话已验证', signOut: '退出登录', operationsCenter: '运营中心',
    workOrderReview: '工单复核', siteOverview: '站点运行概览', slurmCluster: 'Slurm 执行器', offlineEnvironment: '离线执行器',
    syncedAt: '同步于', waitingSync: '等待同步', refreshData: '刷新数据', createInspection: '创建巡检',
    closeNotice: '关闭提示', overview: '任务概况', inspectionFlow: '巡检工作流',
    phaseCreated: '任务创建', phaseExecution: '执行作业', phaseResults: '结果入库', phaseReview: '人工复核',
    missionRecords: '任务记录', executing: '执行中', activeMissions: '当前活动任务',
    pendingOrders: '待复核工单', needsConfirmation: '需要人工确认', totalCompleted: '累计完成',
    resultsValidated: '结果已校验入库', executionEnvironment: '执行环境', offlineAdapter: '离线适配器',
    simulationRobot: '仿真机器人', missionActivity: '任务运行记录', recentFirst: '按最近提交时间排列 · 每 8 秒同步',
    showing: '显示', records: '条', all: '全部', inProgress: '进行中', attention: '需关注', ended: '已结束',
    filterMissions: '任务状态筛选', searchMission: '搜索任务', searchPlaceholder: '搜索任务 ID 或作业号',
    taskRunId: '任务 / 运行 ID', runStatus: '运行状态', executor: '执行器', createdAt: '创建时间',
    actions: '操作', viewMission: '查看任务详情', loadingMissions: '正在加载任务…', noMatchingMissions: '没有符合条件的任务',
    loadEarlier: '加载更早记录', loadingEarlier: '正在加载…',
    noMissions: '暂无任务记录', recentReview: '最近待复核', latestAlerts: '仅展示最新 5 条待处理告警',
    viewAll: '查看全部', noPendingOrders: '当前没有待复核工单', reviewQueue: '人工复核队列',
    reviewSafety: '告警不会触发现场动作；仅已人工确认的工单可由管理员显式提交到 EAM 适配器。', pendingCount: '条待处理',
    pending: '待复核', acknowledged: '已确认', dismissed: '已驳回', inspectEvidence: '请查看原始巡检观测并人工判断。',
    reviewComment: '填写复核意见', reject: '驳回', confirm: '确认', noOrders: '还没有工单', eamSubmit: '提交 EAM', eamRetry: '重试 EAM', eamSubmitting: '正在提交 EAM…', eamNotSubmitted: '尚未提交 EAM', eamPending: 'EAM 提交处理中', eamSubmitted: 'EAM 已提交', eamFailed: 'EAM 提交失败，可重试', eamExternalId: '外部工单号', eamRequiresAdmin: '仅管理员可提交 EAM',
    orderSource: '巡检结果中的告警会出现在这里。', auditTrail: '系统审计轨迹',
    auditDescription: '任务创建、状态变更、结果导入与人工复核事件', refresh: '刷新', noAudit: '暂无审计记录',
    auditPermission: '访问需要管理员或复核员权限。', persistence: '数据库目标：Supabase PostgreSQL', localPersistence: '本地演示：SQLite + 本地制品目录',
    provenance: '来源标签与仿真边界随每次任务保存', newRun: '新建巡检任务', createMissionTitle: '创建巡检任务',
    site: '站点', waypoints: '巡检点位', seed: '仿真随机种子', simulationDisclaimer: '当前 runner 输出标记为',
    virtualWorldRender: '生成本地虚拟场景', virtualWorldRenderHint: '附带 Blender 3D 场景、GLB、多机位和逐航点 PNG；不是实际传感器图像。',
    syntheticOnly: '并非 Isaac Sim 或现场测量结果。', cancel: '取消', submitting: '提交中…',
    submitSlurm: '提交到 Slurm', createOfflineMission: '创建离线任务', missionDetail: '任务详情',
    waitingSubmit: '待提交', loadingMissionDetail: '加载任务详情…', cancelMission: '取消任务',
    cancelMissionConfirm: '取消巡检任务', reviewCommentMin: '复核意见至少填写 3 个字符。',
    executionTrace: '执行轨迹', resultEvidence: '点位观测与异常证据', generatedArtifacts: '结果文件',
    dataSource: '数据来源', demoScenario: '演示分支', syntheticAnomalyScenario: '隔离合成异常闭环', successfulScenario: '全正常连续流', softwareVersion: '软件版本', configDigest: '配置校验值',
    navigationStatus: '导航状态', inspectionStatus: '巡检状态', dataQuality: '数据质量',
    pressure: '压力', temperature: '设备温度', ambientTemperature: '环境温度',
    cabinetDoor: '柜门状态', leakSignal: '泄漏指示', closed: '已关闭', open: '未关闭',
    suspected: '疑似', notDetected: '未检出', confidence: '传感置信度',
    visualEvidence: '图像证据', visualUnavailable: '本次结果未附图像文件',
    virtualSceneViewer: '虚拟工厂 3D 场景', virtualSceneDescription: '在浏览器中旋转、缩放并切换本次 Blender 渲染的机位。',
    virtualSceneLoading: '正在加载 3D 场景…', virtualSceneLoadFailed: '3D 场景加载失败', virtualSceneUnavailable: '本次任务没有 Blender GLB 场景。',
    threeDModel: '3D 模型', cameraViews: '多机位画面', overviewCamera: '厂房总览', operatorCamera: '操作员机位', robotFirstPerson: '机器人第一视角', orbitCamera: '环绕机位', waypointCamera: '航点相机', cameraLoading: '正在加载机位画面…', cameraGroupOverview: '总览与操作', cameraGroupCctv: '固定 CCTV', cameraGroupRobot: '机器人视角', cameraGroupOrbit: '环绕机位', cameraGroupDetail: '设备细节', sceneCurrentCamera: '当前机位', sceneIntegrity: '制品完整性', sceneHash: 'SHA-256', sceneSource: '来源', verified: '已校验', sceneTelemetry: '数字孪生运行态', sceneLive: '同步运行', sceneSynced: '已同步', sceneWaitingSync: '等待回放帧', sceneRouteIndex: '路线帧', sceneRenderFrame: '渲染帧', scenePose: '机器人姿态', sceneTwinLayer: '数字孪生联动层', v34Workbench: 'V34 / 数字孪生联动',
    playRobot: '播放机器人路线', pauseRobot: '暂停机器人路线', sceneSyntheticNote: '本地 Blender 合成场景；不代表 Isaac Sim、真实机器狗或现场传感器。', sceneSyntheticLocal: '本地 Blender 合成场景', sceneSyntheticBoundary: '不代表 Isaac Sim、真实机器狗或现场传感器。',
    interactiveSceneLabel: '可旋转的虚拟工厂 3D 场景', synchronizedReplay: '同步巡检回放', synchronizedReplayDescription: '机器人头顶 RGB 图像流、固定仓库 CCTV 和路线位置共用同一条本地仿真时间轴。', robotHeadLoading: '正在加载机器人头顶画面…', fixedCameraLoading: '正在加载固定机位…', cameraViewCount: '个机位', routeFrames: '帧', robotRoute: '机器人路线', plantTopDown: '厂区俯视平面', plantTopDownDescription: '按本地工厂 XY 坐标缩放，设备、通道、区域、航点与机器人位置保持同一平面投影。', plantBoundary: '厂房边界', equipmentZone: '设备区', serviceLane: '机器人通道', processPiping: '工艺管线', plannedRoute: '规划路线', robotPosition: '机器人位置', inspectionWaypoint: '巡检航点', currentInspection: '当前巡检对象', coordinateReference: '本地坐标系 · m', trajectory: '运动轨迹', startPosition: '起始位', robotVideoStream: '机器人视频流', syncFrame: '同步帧', completedRoute: '已走路线', robot: '机器人', waypoint: '航点',
    xCoordinate: '坐标 X', yCoordinate: '坐标 Y', heading: '朝向', status: '当前状态', playing: '运行中', paused: '已暂停', ready: '待播放', robotHeadRgbStream: '机器人头顶 RGB 视频流', warehouseFixedCamera: '仓库固定摄像头视角', sameRouteFrame: '同一路线帧', rgbStreamFrame: 'RGB 视频流帧', fixedCameraReplayFrame: '固定机位回放帧', returnToStart: '回到起点', pauseReplay: '暂停回放', playReplay: '播放回放', nextFrame: '下一帧', playbackSpeed: '播放速度', synchronizedReplayProgress: '同步回放进度', waypointProgress: '航点', currentFinding: '当前告警', noFindingAtFrame: '当前帧无规则告警', trajectoryFallback: '轨迹制品读取失败，使用降级路线', imageStreamFallback: '同步图像流不可用，使用航点画面', localBlenderStream: '本地 Blender 图像流，不是实时现场视频', localBlenderVideoStream: 'Blender 连续视频流；本地仿真，不是实时现场视频', continuousVideoStream: 'Blender 连续视频流', syncedImageStream: '同步图像流', syntheticReplay: '合成回放', collisionSafeRoute: '避障通道规划', routePlanner: '路线规划器', safetyClearance: '安全缓冲', routeSegments: '通道段', routeDistance: '路线长度', evidenceWorkbench: '证据工作台', evidenceWorkbenchDescription: '当前同步帧的路线、画面来源、渲染帧和制品哈希均可追溯。', filterWaypoint: '航点筛选', filterCamera: '机位筛选', filterEvidence: '证据状态', allWaypoints: '全部航点', allCameraViews: '双路画面', robotOnly: '仅机器人视角', cctvOnly: '仅固定 CCTV', allEvidence: '全部证据', verifiedEvidence: '已校验证据', attentionEvidence: '需要关注', evidenceVerified: '双路已配对', evidenceAttention: '配对不完整', evidenceRouteFrame: '路线帧', evidenceRenderFrame: '渲染帧', evidenceResolution: '图像分辨率', evidenceSource: '制品来源', evidenceHash: '图像哈希', evidenceArtifact: '制品名称', openEvidence: '查看原图', noEvidenceMatch: '当前筛选没有匹配的证据画面', v33Workbench: 'V33 / 可审计证据工作台',
    observationMissing: '未收到该点位观测', anomalyEvidence: '异常证据', noAnomalies: '规则未报告异常',
    traceWaiting: '等待中', traceActive: '处理中', traceComplete: '已完成', traceFailed: '未完成',
    reviewPending: '待人工复核', reviewComplete: '复核已记录', reviewNotRequired: '无需复核',
    artifactsLoading: '正在读取结果文件…', noArtifacts: '没有可下载的结果文件',
    download: '下载', downloadFailed: '下载结果文件失败', artifactLoadFailed: '读取结果文件失败',
    artifactReport: '巡检报告', artifactRun: '巡检数据', artifactOrders: '工单数据',
    anomalyTemperatureCritical: '温度达到严重阈值', anomalyTemperatureHigh: '温度达到预警阈值',
    anomalyDoorOpen: '配电柜柜门未关闭', anomalyPressureCritical: '压力超过配置上限', anomalyPressureHigh: '压力超过配置上限',
    anomalyMeasurementMissing: '必需测量缺失',
    anomalyLeakSuspected: '输入标记为疑似泄漏', recommendationTemperature: '安排具备资质的人员复核温度读数、设备负载和测量条件；本系统不控制设备。',
    recommendationDoor: '由授权人员确认柜门状态及现场作业安全条件。',
    recommendationPressure: '安排具备资质的人员核对压力读数和设备工况；本系统不执行设备联动。',
    recommendationMissing: '必需测量缺失，不能判定设备正常；重新采集数据并由人工复核。',
    recommendationLeak: '按疑似泄漏处理，由人员结合独立证据复核后再决定现场处置。',
    language: '界面语言', mainNavigation: '主导航', chinese: '中文', english: 'EN', unknownStatus: '未知状态', close: '关闭', reviewedBy: '由',
    loadFailed: '加载失败', createFailed: '任务创建失败', missionReadFailed: '读取任务失败',
    cancelFailed: '取消失败', reviewFailed: '提交复核失败', requestFailed: '请求失败',
    invalidCredentials: '邮箱或密码不正确。', emailNotConfirmed: '邮箱尚未验证。',
    accountRoleRequired: '此账户尚未获得巡检平台访问权限',
    accountRoleExplanation: '登录身份已验证，但平台没有为此账户分配应用角色。请联系系统管理员开通权限后重新登录。',
    signedInAs: '当前登录账户', accessDeniedLabel: '未授予访问权限', sessionVerified: '身份验证通过',
    insufficientRole: '当前操作需要更高的账户权限。',
  },
  en: {
    pageTitle: 'Inspection Operations Console', booting: 'Connecting to identity service', brand: 'Inspection Operations', brandContext: 'SITE OPERATIONS',
    loginTitle: 'Sign in to the console', loginCopy: 'Review site status, create inspection missions, and assess returned findings.', email: 'Email',
    password: 'Password', signIn: 'Sign in', signInProgress: 'Verifying…', authRequestFailed: 'Sign-in is temporarily unavailable. Please try again.', authConfigMissing: 'Supabase Auth is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.',
    accountPolicy: 'Access is verified by the identity service and API role',
    simulationOnly: 'Simulation data, not field measurements',
    simulationPreview: 'SIMULATION WORKFLOW',
    loginOpsTitle: 'Industrial operations', loginOpsCopy: 'Mission status, execution records, and findings awaiting human review.',
    loginSceneTitle: 'Scene & execution', loginSceneCopy: 'Review configured waypoints and offline or Slurm execution records.',
    loginDiagnosisTitle: 'Sensing & diagnostics', loginDiagnosisCopy: 'Review returned readings, quality flags, and rule findings; missing values remain unknown.',
    loginReviewTitle: 'Work orders & audit', loginReviewCopy: 'Human reviews are recorded here; an acknowledged order can be submitted to the optional EAM adapter by an admin.',
    mapCaption: 'Coordinates are from site configuration, not live mapping or robot localization.', mapLegend: 'Configured inspection order',
    sitePoints: 'Configured waypoints', latestRun: 'Latest mission', latestReadings: 'Waypoint observations',
    noRunYet: 'No inspection missions yet', noReadingsYet: 'No waypoint observations were returned for this mission.',
    observedPoints: 'Observations received', reportedFindings: 'Rule findings', configuredRobot: 'Executor configuration',
    openLatestRun: 'Open latest mission details', pointPosition: 'Configured coordinates',
    mapUnavailable: 'No waypoint coordinates are available in the site configuration.',
    scenePageCopy: 'Review configured waypoints, inspection order, and the latest execution. This is not a live Isaac Sim view or robot localization.',
    industrialRegistryTitle: 'Industrial asset register & field readiness',
    industrialRegistryCopy: 'Asset identity, model provenance, sensor contracts, and safety gates come from the industrial site configuration; current data is still local simulation.',
    readinessStatus: 'Readiness', assetRegister: 'Asset register', modelSource: 'Model source',
    inspectionPoints: 'Inspection points', sensorContracts: 'Sensor contracts', sensorSource: 'Source status',
    safetyGate: 'Safety gates', fieldBlockers: 'Field deployment blockers', fieldDataPending: 'Field data pending',
    fieldVerified: 'Field verified', proceduralProxy: 'Procedural proxy', cadPending: 'CAD pending',
    sensorSynthetic: 'Synthetic simulation', sensorNotConnected: 'Not connected', restrictedZone: 'Restricted zones',
    stopConditions: 'Automatic stop conditions', humanReview: 'Human review conditions', noAutomaticActuation: 'No automatic equipment actuation',
    assetCount: 'Assets', sensorCount: 'Sensors', zoneName: 'Zone', modelRevision: 'Model revision',
    diagnosticsPageCopy: 'Review raw readings, data quality, and rule findings by waypoint. Measurements not returned remain unknown.',
    diagnosticReadings: 'Waypoint diagnostics', diagnosticMissingRun: 'The latest mission has not returned diagnostic results.',
    diagnosticNotRun: 'No inspection observations are available. Create a mission and wait for results to appear here.',
    diagnosticSourceNote: 'Rule assessments and simulation observations; not field measurements or model accuracy.',
    findingsCount: 'Findings', assessment: 'Assessment', waypointDevice: 'Inspection asset',
    workflowHeadline: 'Site operations console', workflowCopy: 'Follow the single-site workflow from mission submission to validated results and human review.',
    currentSite: 'Current site', loading: 'Loading', missions: 'Operations', simulationSection: 'Scene & execution', diagnosticsSection: 'Sensing & diagnostics', workOrders: 'Work orders',
    navOperations: '01 / OPERATIONS', navSimulation: '02 / DIGITAL TWIN', navPerception: '03 / PERCEPTION', navCloseout: '04 / EAM CLOSEOUT', eamDisconnected: 'EAM NOT CONNECTED', eamEnabled: 'EAM adapter enabled · vendor validation pending',
    controlDesk: 'SITE CONTROL', currentClock: 'LOCAL CLOCK', executionMode: 'EXECUTION MODE', eamAdapter: 'EAM ADAPTER', workerHeartbeat: 'WORKER HEARTBEAT', databaseStatus: 'DATABASE', connected: 'CONNECTED', simulated: 'OFFLINE SIMULATION', heartbeatNominal: 'HEARTBEAT NOMINAL', renderBackend: 'RENDER BACKEND', framesPerSecond: 'FRAME RATE', packetLoss: 'PACKET LOSS', cameraCode: 'CAMERA CODE', timecode: 'TIMECODE', cabinetStatus: 'FIELD CABINET STATUS',
    slurmJob: 'Slurm job', slurmJobLabel: 'Slurm job', seedShort: 'Seed',
    audit: 'Audit log', apiAuthenticated: 'Signed-in session verified', signOut: 'Sign out', operationsCenter: 'Operations',
    workOrderReview: 'Work order review', siteOverview: 'Site operations overview', slurmCluster: 'Slurm executor', offlineEnvironment: 'Offline executor',
    syncedAt: 'Synced', waitingSync: 'Waiting for sync', refreshData: 'Refresh data', createInspection: 'New inspection',
    closeNotice: 'Dismiss notice', overview: 'Mission overview', inspectionFlow: 'Inspection workflow',
    phaseCreated: 'Mission created', phaseExecution: 'Execution job', phaseResults: 'Result stored', phaseReview: 'Human review',
    missionRecords: 'mission records', executing: 'Running', activeMissions: 'Active missions',
    pendingOrders: 'Pending reviews', needsConfirmation: 'Require human confirmation', totalCompleted: 'Completed',
    resultsValidated: 'Results validated and stored', executionEnvironment: 'Execution environment', offlineAdapter: 'Offline adapter',
    simulationRobot: 'Simulation robot', missionActivity: 'Mission activity', recentFirst: 'Most recently submitted first · Syncs every 8 seconds',
    showing: 'Showing', records: 'records', all: 'All', inProgress: 'In progress', attention: 'Needs attention', ended: 'Ended',
    filterMissions: 'Filter missions by status', searchMission: 'Search missions', searchPlaceholder: 'Search mission ID or job ID',
    taskRunId: 'Mission / run ID', runStatus: 'Status', executor: 'Executor', createdAt: 'Created',
    actions: 'Actions', viewMission: 'View mission details', loadingMissions: 'Loading missions…', noMatchingMissions: 'No missions match your filters',
    loadEarlier: 'Load older records', loadingEarlier: 'Loading…',
    noMissions: 'No mission records', recentReview: 'Recent reviews', latestAlerts: 'Latest 5 alerts awaiting review',
    viewAll: 'View all', noPendingOrders: 'No reviews are pending', reviewQueue: 'Human review queue',
    reviewSafety: 'Alerts do not trigger field actions. Only an acknowledged order can be explicitly submitted to the EAM adapter by an admin.', pendingCount: 'pending',
    pending: 'Pending review', acknowledged: 'Acknowledged', dismissed: 'Dismissed', inspectEvidence: 'Review the original inspection observations and assess manually.',
    reviewComment: 'Add a review comment', reject: 'Dismiss', confirm: 'Acknowledge', noOrders: 'No work orders', eamSubmit: 'Submit to EAM', eamRetry: 'Retry EAM', eamSubmitting: 'Submitting to EAM…', eamNotSubmitted: 'Not submitted to EAM', eamPending: 'EAM submission in progress', eamSubmitted: 'Submitted to EAM', eamFailed: 'EAM submission failed; retry is safe', eamExternalId: 'External work-order ID', eamRequiresAdmin: 'Only admin can submit to EAM',
    orderSource: 'Alerts from inspection results will appear here.', auditTrail: 'System audit trail',
    auditDescription: 'Mission creation, status changes, result imports, and human review events', refresh: 'Refresh', noAudit: 'No audit records',
    auditPermission: 'Admin or reviewer access is required.', persistence: 'Database target: Supabase PostgreSQL', localPersistence: 'Local demo: SQLite + local artifact directory',
    provenance: 'Source labels and simulation boundaries are saved with every mission', newRun: 'New inspection run', createMissionTitle: 'Create inspection mission',
    site: 'Site', waypoints: 'Inspection waypoints', seed: 'Simulation random seed', simulationDisclaimer: 'Current runner output is tagged as',
    virtualWorldRender: 'Render local virtual scene', virtualWorldRenderHint: 'Attach a Blender 3D scene, GLB, multi-camera renders, and per-waypoint PNGs; these are not real sensor images.',
    syntheticOnly: 'It is not an Isaac Sim or field measurement result.', cancel: 'Cancel', submitting: 'Submitting…',
    submitSlurm: 'Submit to Slurm', createOfflineMission: 'Create offline mission', missionDetail: 'Mission details',
    waitingSubmit: 'Awaiting submission', loadingMissionDetail: 'Loading mission details…', cancelMission: 'Cancel mission',
    cancelMissionConfirm: 'Cancel inspection mission', reviewCommentMin: 'Review comments must be at least 3 characters.',
    executionTrace: 'Execution trace', resultEvidence: 'Waypoint observations and findings', generatedArtifacts: 'Result files',
    dataSource: 'Data source', demoScenario: 'Demo branch', syntheticAnomalyScenario: 'Isolated synthetic anomaly closeout', successfulScenario: 'All-normal continuous stream', softwareVersion: 'Software version', configDigest: 'Configuration checksum',
    navigationStatus: 'Navigation', inspectionStatus: 'Inspection', dataQuality: 'Data quality',
    pressure: 'Pressure', temperature: 'Equipment temperature', ambientTemperature: 'Ambient temperature',
    cabinetDoor: 'Cabinet door', leakSignal: 'Leak indicator', closed: 'Closed', open: 'Open',
    suspected: 'Suspected', notDetected: 'Not detected', confidence: 'Sensor confidence',
    visualEvidence: 'Image evidence', visualUnavailable: 'No image artifact was attached to this run',
    virtualSceneViewer: 'Virtual factory 3D scene', virtualSceneDescription: 'Orbit, zoom, and switch between Blender-rendered camera views for this mission.',
    virtualSceneLoading: 'Loading 3D scene…', virtualSceneLoadFailed: 'Failed to load the 3D scene', virtualSceneUnavailable: 'This mission has no Blender GLB scene.',
    threeDModel: '3D model', cameraViews: 'Camera views', overviewCamera: 'Factory overview', operatorCamera: 'Operator camera', robotFirstPerson: 'Robot first person', orbitCamera: 'Orbit camera', waypointCamera: 'Waypoint camera', cameraLoading: 'Loading camera view…', cameraGroupOverview: 'Overview & operator', cameraGroupCctv: 'Fixed CCTV', cameraGroupRobot: 'Robot views', cameraGroupOrbit: 'Orbit views', cameraGroupDetail: 'Equipment detail', sceneCurrentCamera: 'Current camera', sceneIntegrity: 'Artifact integrity', sceneHash: 'SHA-256', sceneSource: 'Source', verified: 'Verified', sceneTelemetry: 'Digital twin telemetry', sceneLive: 'Sync state', sceneSynced: 'Synchronized', sceneWaitingSync: 'Waiting for replay frame', sceneRouteIndex: 'Route frame', sceneRenderFrame: 'Render frame', scenePose: 'Robot pose', sceneTwinLayer: 'Scene linkage layer', v34Workbench: 'V34 / DIGITAL TWIN LINKAGE',
    playRobot: 'Play robot route', pauseRobot: 'Pause robot route', sceneSyntheticNote: 'Local Blender synthetic scene; not Isaac Sim, a physical robot, or field sensor data.', sceneSyntheticLocal: 'Local Blender synthetic scene', sceneSyntheticBoundary: 'Not Isaac Sim, a physical robot, or field sensor data.',
    interactiveSceneLabel: 'Interactive virtual factory 3D scene', synchronizedReplay: 'Synchronized inspection replay', synchronizedReplayDescription: 'The robot-head RGB stream, fixed warehouse CCTV, and route position share one local simulation timeline.', robotHeadLoading: 'Loading robot-head view…', fixedCameraLoading: 'Loading fixed camera…', cameraViewCount: 'camera views', routeFrames: 'frames', robotRoute: 'Robot route', plantTopDown: 'Plant top-down plan', plantTopDownDescription: 'Scaled to the local plant XY coordinate system so equipment, lanes, zones, waypoints, and robot pose share one plan projection.', plantBoundary: 'Plant boundary', equipmentZone: 'Equipment zone', serviceLane: 'Robot service lane', processPiping: 'Process piping', plannedRoute: 'Planned route', robotPosition: 'Robot position', inspectionWaypoint: 'Inspection waypoint', currentInspection: 'Current inspection', coordinateReference: 'Local coordinates · m', trajectory: 'Trajectory', startPosition: 'Start', robotVideoStream: 'Robot video stream', syncFrame: 'Sync frame', completedRoute: 'Completed', robot: 'Robot', waypoint: 'Waypoint',
    xCoordinate: 'X coordinate', yCoordinate: 'Y coordinate', heading: 'Heading', status: 'Status', playing: 'Playing', paused: 'Paused', ready: 'Ready', robotHeadRgbStream: 'Robot-head RGB stream', warehouseFixedCamera: 'Warehouse fixed camera', sameRouteFrame: 'SAME ROUTE FRAME', rgbStreamFrame: 'RGB STREAM FRAME', fixedCameraReplayFrame: 'FIXED CAMERA REPLAY FRAME', returnToStart: 'Return to start', pauseReplay: 'Pause replay', playReplay: 'Play replay', nextFrame: 'Next frame', playbackSpeed: 'Playback speed', synchronizedReplayProgress: 'Synchronized replay progress', waypointProgress: 'Waypoint', currentFinding: 'Current finding', noFindingAtFrame: 'No rule finding at current frame', trajectoryFallback: 'Trajectory artifact unavailable; using fallback route', imageStreamFallback: 'Image stream unavailable; using waypoint stills', localBlenderStream: 'Local Blender image stream, not live field video', localBlenderVideoStream: 'Continuous Blender video stream; local simulation, not live field video', continuousVideoStream: 'Continuous Blender video stream', syncedImageStream: 'Synced image stream', syntheticReplay: 'Synthetic replay', collisionSafeRoute: 'Collision-safe aisle planning', routePlanner: 'Route planner', safetyClearance: 'Safety clearance', routeSegments: 'Aisle segments', routeDistance: 'Route length', evidenceWorkbench: 'Evidence workbench', evidenceWorkbenchDescription: 'The current synchronized frame exposes route position, camera provenance, render frame, and artifact hashes.', filterWaypoint: 'Waypoint filter', filterCamera: 'Camera filter', filterEvidence: 'Evidence status', allWaypoints: 'All waypoints', allCameraViews: 'Paired views', robotOnly: 'Robot view only', cctvOnly: 'Fixed CCTV only', allEvidence: 'All evidence', verifiedEvidence: 'Verified evidence', attentionEvidence: 'Needs attention', evidenceVerified: 'Pair verified', evidenceAttention: 'Pair incomplete', evidenceRouteFrame: 'Route frame', evidenceRenderFrame: 'Render frame', evidenceResolution: 'Image resolution', evidenceSource: 'Artifact source', evidenceHash: 'Image hash', evidenceArtifact: 'Artifact name', openEvidence: 'Open source image', noEvidenceMatch: 'No evidence frames match the active filters', v33Workbench: 'V33 / AUDITABLE EVIDENCE WORKBENCH',
    observationMissing: 'No observation was returned for this waypoint', anomalyEvidence: 'Findings', noAnomalies: 'No rule findings were reported',
    traceWaiting: 'Waiting', traceActive: 'In progress', traceComplete: 'Complete', traceFailed: 'Did not complete',
    reviewPending: 'Awaiting human review', reviewComplete: 'Review recorded', reviewNotRequired: 'No review required',
    artifactsLoading: 'Loading result files…', noArtifacts: 'No result files are available',
    download: 'Download', downloadFailed: 'Failed to download result file', artifactLoadFailed: 'Failed to load result files',
    artifactReport: 'Inspection report', artifactRun: 'Inspection data', artifactOrders: 'Work-order data',
    anomalyTemperatureCritical: 'Temperature reached the critical threshold', anomalyTemperatureHigh: 'Temperature reached the warning threshold',
    anomalyDoorOpen: 'Electrical cabinet door is open', anomalyPressureCritical: 'Pressure exceeded the configured limit',
    anomalyPressureHigh: 'Pressure exceeded the configured limit', anomalyMeasurementMissing: 'Required measurement is missing',
    anomalyLeakSuspected: 'Input indicates a suspected leak', recommendationTemperature: 'Have qualified personnel verify the temperature reading, equipment load, and measurement conditions. This system does not control equipment.',
    recommendationDoor: 'An authorized person must confirm the cabinet state and site safety conditions.',
    recommendationPressure: 'Have qualified personnel verify the pressure reading and operating conditions. This system does not actuate equipment.',
    recommendationMissing: 'Required readings are missing. Do not mark the asset normal; recollect data and request human review.',
    recommendationLeak: 'Treat this as a suspected leak. Personnel must verify it with independent evidence before deciding on a field response.',
    language: 'Interface language', mainNavigation: 'Main navigation', chinese: '中文', english: 'EN', unknownStatus: 'Unknown status', close: 'Close', reviewedBy: 'By',
    loadFailed: 'Failed to load data', createFailed: 'Failed to create mission', missionReadFailed: 'Failed to load mission',
    cancelFailed: 'Failed to cancel mission', reviewFailed: 'Failed to submit review', requestFailed: 'Request failed',
    invalidCredentials: 'Email or password is incorrect.', emailNotConfirmed: 'Email address has not been confirmed.',
    accountRoleRequired: 'This account does not have inspection platform access',
    accountRoleExplanation: 'Your identity is verified, but no application role is assigned to this account. Contact your system administrator, then sign in again.',
    signedInAs: 'Signed in as', accessDeniedLabel: 'ACCESS NOT GRANTED', sessionVerified: 'Identity verified',
    insufficientRole: 'This action requires a higher account role.',
  },
} as const

type MessageKey = keyof typeof messages.zh
const loginModules: ReadonlyArray<{ title: MessageKey; description: MessageKey }> = [
  { title: 'loginOpsTitle', description: 'loginOpsCopy' },
  { title: 'loginSceneTitle', description: 'loginSceneCopy' },
  { title: 'loginDiagnosisTitle', description: 'loginDiagnosisCopy' },
  { title: 'loginReviewTitle', description: 'loginReviewCopy' },
]
const statusLabel: Record<Locale, Record<string, string>> = {
  zh: {
    QUEUED: '排队中', SUBMITTING: '提交中', SUBMITTED: '已提交', PENDING: '等待资源', CANCELLING: '取消中',
    RUNNING: '执行中', IMPORTING: '导入结果', SUCCEEDED: '已完成', PARTIAL: '部分完成 · 需关注', FAILED: '失败',
    CANCELLED: '已取消', TIMED_OUT: '超时', RESULT_IMPORT_FAILED: '结果导入失败',
    NAVIGATING: '导航中', INSPECTING: '采集中', COMPLETED: '已完成', SKIPPED: '已跳过',
  },
  en: {
    QUEUED: 'Queued', SUBMITTING: 'Submitting', SUBMITTED: 'Submitted', PENDING: 'Pending resources', CANCELLING: 'Cancelling',
    RUNNING: 'Running', IMPORTING: 'Importing results', SUCCEEDED: 'Succeeded', PARTIAL: 'Partial · review needed', FAILED: 'Failed',
    CANCELLED: 'Cancelled', TIMED_OUT: 'Timed out', RESULT_IMPORT_FAILED: 'Result import failed',
    NAVIGATING: 'Navigating', INSPECTING: 'Capturing', COMPLETED: 'Completed', SKIPPED: 'Skipped',
  },
}
const severityLabel: Record<Locale, Record<string, string>> = {
  zh: { CRITICAL: '严重', WARNING: '预警', HIGH: '高', MEDIUM: '中', LOW: '低', NORMAL: '正常', UNKNOWN: '未知' },
  en: { CRITICAL: 'Critical', WARNING: 'Warning', HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', NORMAL: 'Normal', UNKNOWN: 'Unknown' },
}
const statusTone: Record<string, string> = {
  QUEUED: 'muted', SUBMITTING: 'blue', SUBMITTED: 'blue', PENDING: 'blue', RUNNING: 'green',
  IMPORTING: 'blue', CANCELLING: 'amber', SUCCEEDED: 'green', PARTIAL: 'amber', FAILED: 'red', CANCELLED: 'muted',
  TIMED_OUT: 'amber', RESULT_IMPORT_FAILED: 'red',
}
const workerStatusLabel: Record<Locale, Record<string, string>> = {
  zh: {
    starting: 'Worker 启动中', working: 'Worker 执行中', idle: 'Worker 在线',
    degraded: 'Worker 异常', stale: 'Worker 心跳过期', stopped: 'Worker 已停止',
    not_seen: 'Worker 未连接',
  },
  en: {
    starting: 'Worker starting', working: 'Worker working', idle: 'Worker online',
    degraded: 'Worker degraded', stale: 'Worker heartbeat stale', stopped: 'Worker stopped',
    not_seen: 'Worker not seen',
  },
}
const workerStatusTone: Record<string, string> = {
  starting: 'blue', working: 'blue', idle: 'green', degraded: 'red',
  stale: 'amber', stopped: 'muted', not_seen: 'muted',
}

class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string | null) {
    super(message)
    this.name = 'ApiError'
  }
}

async function apiResponse(path: string, token: string, locale: Locale, init?: RequestInit) {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Accept-Language': locale === 'zh' ? 'zh-CN' : 'en-US',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    const detailCode = typeof detail === 'object' && detail ? detail.code : null
    const code = typeof detailCode === 'string' ? detailCode : response.headers.get('X-Error-Code')
    const message = code === 'INSUFFICIENT_ROLE'
      ? messages[locale].insufficientRole
      : typeof detail === 'string' ? detail
        : typeof detail?.message === 'string' ? detail.message
          : `${locale === 'zh' ? '请求失败' : 'Request failed'} (${response.status})`
    throw new ApiError(message, response.status, typeof code === 'string' ? code : null)
  }
  return response
}

async function api<T>(path: string, token: string, locale: Locale, init?: RequestInit): Promise<T> {
  const response = await apiResponse(path, token, locale, init)
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

async function apiHistoryPage<T>(path: string, token: string, locale: Locale): Promise<HistoryPage<T>> {
  const response = await apiResponse(path, token, locale)
  return {
    items: await response.json() as T[],
    nextCursor: response.headers.get('X-Next-Cursor'),
  }
}

function mergeHistory<T>(primary: T[], secondary: T[], key: (item: T) => string): T[] {
  const primaryByKey = new Map(primary.map((item) => [key(item), item]))
  const merged = primary.slice()
  for (const item of secondary) {
    const itemKey = key(item)
    if (!primaryByKey.has(itemKey)) {
      primaryByKey.set(itemKey, item)
      merged.push(item)
    }
  }
  return merged.map((item) => primaryByKey.get(key(item)) || item)
}

function formatTime(value: string | null | undefined, locale: Locale) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function formatBytes(size: number, locale: Locale) {
  if (size < 1024) return `${size} B`
  const unit = size < 1024 * 1024 ? 'KB' : 'MB'
  const value = size < 1024 * 1024 ? size / 1024 : size / (1024 * 1024)
  return `${new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { maximumFractionDigits: 1 }).format(value)} ${unit}`
}

function measurement(value: number | null | undefined, unit: string, locale: Locale, digits = 1) {
  if (value == null || !Number.isFinite(value)) return locale === 'zh' ? '未知' : 'Unknown'
  return `${new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value)} ${unit}`
}

function qualityLabel(value: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    USABLE: { zh: '可用', en: 'Usable' },
    PARTIAL: { zh: '部分可用', en: 'Partial' },
    NO_USABLE_MEASUREMENTS: { zh: '无可用测量', en: 'No usable readings' },
  }
  return labels[value]?.[locale] || value
}

function sourceLabel(source: string | undefined, locale: Locale) {
  if (source === 'synthetic_simulation') return locale === 'zh' ? '仿真数据' : 'Simulation data'
  if (source === 'deterministic_rule_engine') return locale === 'zh' ? '确定性规则引擎' : 'Deterministic rules'
  return source || (locale === 'zh' ? '未知' : 'Unknown')
}

function industrialModelLabel(status: string, locale: Locale) {
  if (status === 'procedural_proxy') return locale === 'zh' ? '程序化代理' : 'Procedural proxy'
  if (status === 'cad_pending') return locale === 'zh' ? 'CAD 待补齐' : 'CAD pending'
  if (status === 'field_verified') return locale === 'zh' ? '现场已验证' : 'Field verified'
  return status
}

function industrialSensorLabel(status: string, locale: Locale) {
  if (status === 'synthetic_simulation') return locale === 'zh' ? '合成仿真' : 'Synthetic simulation'
  if (status === 'not_connected') return locale === 'zh' ? '未接入' : 'Not connected'
  if (status === 'field_verified') return locale === 'zh' ? '现场已验证' : 'Field verified'
  return status
}

type LocalizedCatalog = Record<string, Record<Locale, string>>

const siteNameCatalog: LocalizedCatalog = {
  '示例连续工艺车间 A 区': { zh: '示例连续工艺车间 A 区', en: 'Example Continuous Process Plant · Area A' },
}
const robotModelCatalog: LocalizedCatalog = {
  'Quadruped inspection adapter (simulation)': { zh: '四足巡检适配器（仿真）', en: 'Quadruped inspection adapter (simulation)' },
}
const zoneCatalog: LocalizedCatalog = {
  '蒸汽与分离器区': { zh: '蒸汽与分离器区', en: 'Steam & separation area' },
  '换热与过滤区': { zh: '换热与过滤区', en: 'Heat exchange & filtration area' },
  '低压配电区': { zh: '低压配电区', en: 'Low-voltage electrical area' },
  '消防与应急设施区': { zh: '消防与应急设施区', en: 'Fire & emergency systems area' },
  '维护与备件区': { zh: '维护与备件区', en: 'Maintenance & spares area' },
  '模拟管廊 A 区': { zh: '模拟管廊 A 区', en: 'Simulated pipe rack · Area A' },
  '模拟配电房 B 区': { zh: '模拟配电房 B 区', en: 'Simulated electrical room · Area B' },
  '模拟泵房 C 区': { zh: '模拟泵房 C 区', en: 'Simulated pump room · Area C' },
}
const deviceCatalog: LocalizedCatalog = {
  '蒸汽主管道压力表与法兰': { zh: '蒸汽主管道压力表与法兰', en: 'Steam header pressure gauge & flange' },
  '蒸汽主管道压力表与隔离阀组': { zh: '蒸汽主管道压力表与隔离阀组', en: 'Steam header pressure gauge & isolation valve set' },
  'V-101 立式分离器': { zh: 'V-101 立式分离器', en: 'V-101 vertical separator' },
  '低压配电柜 MCC-04': { zh: '低压配电柜 MCC-04', en: 'Low-voltage switchboard MCC-04' },
  '低压配电柜 4 号柜': { zh: '低压配电柜 4 号柜', en: 'Low-voltage switchboard · Cabinet 04' },
  '循环泵组 P-021': { zh: '循环泵组 P-021', en: 'Circulation pump skid P-021' },
  'E-201 壳管式换热器': { zh: 'E-201 壳管式换热器', en: 'E-201 shell-and-tube exchanger' },
  'F-301 循环水过滤器': { zh: 'F-301 循环水过滤器', en: 'F-301 circulation-water filter' },
  '北墙轴流排风机': { zh: '北墙轴流排风机', en: 'North-wall axial exhaust fan' },
  '东墙消防水带盘': { zh: '东墙消防水带盘', en: 'East-wall fire hose reel' },
  '维修工位与备件架': { zh: '维修工位与备件架', en: 'Maintenance bay & spare-parts rack' },
  '上部检修天车': { zh: '上部检修天车', en: 'Overhead maintenance crane' },
}
const assetTypeCatalog: LocalizedCatalog = {
  steam_header: { zh: '蒸汽主管道', en: 'Steam header' },
  vertical_separator: { zh: '立式分离器', en: 'Vertical separator' },
  low_voltage_switchboard: { zh: '低压配电柜', en: 'Low-voltage switchboard' },
  centrifugal_pump: { zh: '离心泵', en: 'Centrifugal pump' },
  shell_tube_exchanger: { zh: '壳管式换热器', en: 'Shell-and-tube exchanger' },
  filter_pump_skid: { zh: '过滤泵撬', en: 'Filter pump skid' },
  axial_exhaust_fan: { zh: '轴流排风机', en: 'Axial exhaust fan' },
  fire_hose_reel: { zh: '消防水带盘', en: 'Fire hose reel' },
  maintenance_bay: { zh: '维修工位', en: 'Maintenance bay' },
  overhead_crane: { zh: '检修天车', en: 'Overhead crane' },
}
const operatingModeCatalog: LocalizedCatalog = {
  commissioning_simulation: { zh: '调试仿真', en: 'Commissioning simulation' },
}
const coordinateSystemCatalog: LocalizedCatalog = {
  local_plant_xy_z_up: { zh: '厂区本地 XY / Z 向上', en: 'Local plant XY / Z-up' },
}
const unitSystemCatalog: LocalizedCatalog = {
  metre_celsius_bar: { zh: '米 · 摄氏度 · bar', en: 'Metre · Celsius · bar' },
}
const sensorChannelCatalog: LocalizedCatalog = {
  visual_inspection: { zh: '视觉巡检', en: 'Visual inspection' },
  surface_temperature: { zh: '表面温度', en: 'Surface temperature' },
  pressure: { zh: '压力', en: 'Pressure' },
  rms_vibration: { zh: '均方根振动', en: 'RMS vibration' },
}
const calibrationCatalog: LocalizedCatalog = {
  pending: { zh: '待标定', en: 'Pending calibration' },
  not_verified: { zh: '未核验', en: 'Not verified' },
}
const safetyCodeCatalog: LocalizedCatalog = {
  'ELEC-B': { zh: '低压配电区', en: 'Low-voltage electrical area' },
  person_detected: { zh: '检测到人员', en: 'Person detected' },
  fire_alarm: { zh: '火灾报警', en: 'Fire alarm' },
  blocked_egress: { zh: '疏散通道受阻', en: 'Blocked egress' },
  loss_of_localization: { zh: '定位丢失', en: 'Loss of localization' },
  critical_alarm: { zh: '严重告警', en: 'Critical alarm' },
  leak_suspected: { zh: '疑似泄漏', en: 'Suspected leak' },
  thermal_hotspot: { zh: '热异常点', en: 'Thermal hotspot' },
  safety_equipment_obstructed: { zh: '安全设备被遮挡', en: 'Safety equipment obstructed' },
}
const auditEventCatalog: LocalizedCatalog = {
  MISSION_CREATED: { zh: '任务已创建', en: 'Mission created' },
  MISSION_SUBMITTED: { zh: '任务已提交', en: 'Mission submitted' },
  MISSION_STATUS_CHANGED: { zh: '任务状态变更', en: 'Mission status changed' },
  MISSION_RESULT_IMPORTED: { zh: '任务结果已导入', en: 'Mission result imported' },
  WORK_ORDER_REVIEWED: { zh: '工单已复核', en: 'Work order reviewed' },
  EAM_SUBMITTED: { zh: '已提交 EAM', en: 'Submitted to EAM' },
}
const roleCatalog: LocalizedCatalog = {
  admin: { zh: '管理员', en: 'Admin' },
  operator: { zh: '操作员', en: 'Operator' },
  reviewer: { zh: '复核员', en: 'Reviewer' },
  viewer: { zh: '查看者', en: 'Viewer' },
}
const fieldBlockerCatalog: LocalizedCatalog = {
  'CAD or scan provenance is not field_verified.': { zh: 'CAD 或扫描数据来源尚未完成现场核验。', en: 'CAD or scan provenance is not field_verified.' },
  'Sensor calibration and live gateway bindings are not field_verified.': { zh: '传感器标定与实时网关绑定尚未完成现场核验。', en: 'Sensor calibration and live gateway bindings are not field_verified.' },
  'Safety acceptance and site commissioning evidence are required.': { zh: '仍需补齐安全验收与站点调试证据。', en: 'Safety acceptance and site commissioning evidence are required.' },
}

function catalogLabel(catalog: LocalizedCatalog, value: string | null | undefined, locale: Locale) {
  if (!value) return ''
  return catalog[value]?.[locale] || value
}

function siteNameLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(siteNameCatalog, value, locale)
}

function robotModelLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(robotModelCatalog, value, locale)
}

function zoneLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(zoneCatalog, value, locale)
}

function deviceLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(deviceCatalog, value, locale)
}

function assetTypeLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(assetTypeCatalog, value, locale)
}

function operatingModeLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(operatingModeCatalog, value, locale)
}

function coordinateSystemLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(coordinateSystemCatalog, value, locale)
}

function unitSystemLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(unitSystemCatalog, value, locale)
}

function sensorChannelLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(sensorChannelCatalog, value, locale)
}

function calibrationLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(calibrationCatalog, value, locale)
}

function safetyCodeLabel(value: string | null | undefined, locale: Locale) {
  return catalogLabel(safetyCodeCatalog, value, locale)
}

function auditEventLabel(value: string, locale: Locale) {
  return catalogLabel(auditEventCatalog, value, locale)
}

function roleLabel(value: string, locale: Locale) {
  return catalogLabel(roleCatalog, value, locale)
}

function fieldBlockerLabel(value: string, locale: Locale) {
  return catalogLabel(fieldBlockerCatalog, value, locale)
}

function resourceTypeLabel(value: string, locale: Locale) {
  const labels: LocalizedCatalog = {
    mission: { zh: '任务', en: 'Mission' },
    work_order: { zh: '工单', en: 'Work order' },
    artifact: { zh: '结果文件', en: 'Artifact' },
    audit_event: { zh: '审计事件', en: 'Audit event' },
  }
  return catalogLabel(labels, value, locale)
}

function localizedRecommendation(value: string, locale: Locale, translate: (key: MessageKey) => string) {
  if (locale === 'zh') return value
  const known: Array<[string, MessageKey]> = [
    [messages.zh.recommendationTemperature, 'recommendationTemperature'],
    [messages.zh.recommendationDoor, 'recommendationDoor'],
    [messages.zh.recommendationPressure, 'recommendationPressure'],
    [messages.zh.recommendationMissing, 'recommendationMissing'],
    [messages.zh.recommendationLeak, 'recommendationLeak'],
    [messages.zh.inspectEvidence, 'inspectEvidence'],
  ]
  const match = known.find(([source]) => source === value)
  return match ? translate(match[1]) : value
}

function artifactLabel(name: string, locale: Locale) {
  const labels: Record<string, Record<Locale, string>> = {
    'inspection_report.md': { zh: '巡检报告', en: 'Inspection report' },
    'inspection_run.json': { zh: '巡检数据', en: 'Inspection data' },
    'work_orders.json': { zh: '工单数据', en: 'Work-order data' },
  }
  return labels[name]?.[locale] || name
}

function anomalyTitle(code: string, locale: Locale, fallback: string) {
  const keys: Record<string, MessageKey> = {
    TEMPERATURE_CRITICAL: 'anomalyTemperatureCritical',
    TEMPERATURE_HIGH: 'anomalyTemperatureHigh',
    CABINET_DOOR_OPEN: 'anomalyDoorOpen',
    PRESSURE_CRITICAL: 'anomalyPressureCritical',
    PRESSURE_HIGH: 'anomalyPressureHigh',
    MEASUREMENT_MISSING: 'anomalyMeasurementMissing',
    LEAK_SUSPECTED: 'anomalyLeakSuspected',
  }
  const key = keys[code]
  return key ? messages[locale][key] : fallback
}

function anomalyDescription(anomaly: Anomaly, locale: Locale) {
  if (locale === 'zh') return anomaly.message
  const evidence = anomaly.evidence || {}
  const value = (key: string) => typeof evidence[key] === 'number' ? evidence[key] as number : '—'
  switch (anomaly.code) {
    case 'TEMPERATURE_CRITICAL':
    case 'TEMPERATURE_HIGH':
      return `Reading ${value('temperature_c')} °C; threshold ${value(anomaly.code === 'TEMPERATURE_CRITICAL' ? 'critical_threshold_c' : 'warning_threshold_c')} °C.`
    case 'CABINET_DOOR_OPEN':
      return 'The asset register requires the cabinet door to be closed; the reported state is open.'
    case 'PRESSURE_CRITICAL':
    case 'PRESSURE_HIGH':
      return `Reading ${value('pressure_mpa')} MPa; configured maximum ${value('configured_max_mpa')} MPa.`
    case 'MEASUREMENT_MISSING':
      return 'One or more required readings are unavailable. The asset cannot be classified as normal.'
    case 'LEAK_SUSPECTED':
      return 'The input indicates a suspected leak. Human review is required; this system does not trigger equipment actions.'
    default:
      return anomaly.message
  }
}

function Status({ value, locale, unknownLabel }: { value: string; locale: Locale; unknownLabel: string }) {
  return <span className={`status status-${statusTone[value] || 'muted'}`}><i />{statusLabel[locale][value] || (value === 'UNKNOWN' ? unknownLabel : value)}</span>
}

function virtualCameraLabel(name: string, locale: Locale) {
  if (name === 'factory_overview.png') return locale === 'zh' ? '厂房总览' : 'Factory overview'
  if (name === 'factory_operator.png') return locale === 'zh' ? '操作员机位' : 'Operator camera'
  const heroLabels: Record<string, [string, string]> = {
    'factory_hero_valve_station.png': ['阀门展示机位', 'Valve hero view'],
    'factory_hero_mcc.png': ['MCC 展示机位', 'MCC hero view'],
    'factory_hero_pump.png': ['泵组展示机位', 'Pump hero view'],
    'factory_hero_instrument.png': ['仪表展示机位', 'Instrument hero view'],
    'factory_hero_valve_macro.png': ['阀门宏观特写', 'Valve macro view'],
    'factory_hero_gauge_macro.png': ['压力表宏观特写', 'Gauge macro view'],
    'factory_hero_mcc_interior.png': ['MCC 柜内特写', 'MCC interior view'],
    'factory_hero_mcc_macro.png': ['MCC 柜门特写', 'MCC macro view'],
    'factory_hero_pump_macro.png': ['泵组机械特写', 'Pump macro view'],
    'factory_hero_wide.png': ['厂房展示总览', 'Wide hero view'],
  }
  if (heroLabels[name]) return locale === 'zh' ? heroLabels[name][0] : heroLabels[name][1]
  if (name.startsWith('factory_cctv__')) {
    const waypoint = name.replace('factory_cctv__', '').replace('.png', '')
    return `${locale === 'zh' ? '仓库固定机位' : 'Warehouse CCTV'} · ${waypoint}`
  }
  if (name === 'factory_robot_first_person.png') return locale === 'zh' ? '机器人第一视角' : 'Robot first person'
  if (/^factory_orbit_\d+\.png$/.test(name)) {
    return `${locale === 'zh' ? '环绕机位' : 'Orbit camera'} ${name.match(/\d+/)?.[0] || ''}`
  }
  if (name.startsWith('factory_detail_') && name.endsWith('.png')) {
    const waypoint = name.replace('factory_detail_', '').replace('.png', '').toUpperCase()
    return `${locale === 'zh' ? '设备特写' : 'Equipment detail'} · ${waypoint}`
  }
  if (name.startsWith('virtual_world__')) {
    const waypoint = name.replace('virtual_world__', '').replace('__rgb_camera.png', '')
    return `${locale === 'zh' ? '航点相机' : 'Waypoint camera'} · ${waypoint}`
  }
  return name
}

type CameraGroupKey = 'overview' | 'cctv' | 'robot' | 'orbit' | 'detail' | 'other'

function cameraGroupForName(name: string): CameraGroupKey {
  if (name === 'factory_overview.png' || name === 'factory_operator.png' || name === 'factory_aerial.png'
    || name === 'factory_low_operator.png' || name === 'factory_asset_map.png' || name === 'factory_process_floor.png') return 'overview'
  if (name.startsWith('factory_cctv__')) return 'cctv'
  if (name === 'factory_robot_first_person.png' || name.startsWith('virtual_world__')) return 'robot'
  if (name.startsWith('factory_orbit_')) return 'orbit'
  if (name.startsWith('factory_detail_') || name.startsWith('factory_hero_') || name === 'factory_cable_tray.png'
    || name === 'factory_electrical_boundary.png' || name === 'factory_floor_services.png'
    || name === 'factory_instrument_air.png' || name === 'factory_pipe_rack_upward.png'
    || name === 'factory_pump_maintenance.png' || name === 'factory_valve_station.png') return 'detail'
  return 'other'
}

function cameraGroupLabel(key: CameraGroupKey, locale: Locale) {
  const labels: Record<CameraGroupKey, [MessageKey, string]> = {
    overview: ['cameraGroupOverview', 'Overview'],
    cctv: ['cameraGroupCctv', 'CCTV'],
    robot: ['cameraGroupRobot', 'Robot'],
    orbit: ['cameraGroupOrbit', 'Orbit'],
    detail: ['cameraGroupDetail', 'Detail'],
    other: ['cameraViews', 'Other'],
  }
  const [messageKey, fallback] = labels[key]
  return messages[locale][messageKey] || fallback
}

function virtualCameraRank(name: string) {
  if (name === 'factory_overview.png') return 0
  if (name === 'factory_operator.png') return 1
  if (name === 'factory_robot_first_person.png') return 2
  if (name.startsWith('factory_hero_')) return 3
  if (/^factory_orbit_\d+\.png$/.test(name)) return 4
  if (name.startsWith('factory_cctv__')) return 5
  if (name.startsWith('virtual_world__')) return 6
  if (name.startsWith('factory_detail_')) return 7
  return 8
}

type SurfaceDetailMaps = {
  albedo: THREE.CanvasTexture
  roughness: THREE.DataTexture
  normal: THREE.DataTexture
}

function surfaceKindForMaterial(name: string) {
  const material = name.toLowerCase()
  if (/concrete|floor|dust|grime|stain/.test(material)) return 'concrete'
  if (/steel|metal|stainless|pipe|fastener|brass|copper/.test(material)) return 'metal'
  if (/rubber|gasket|seal|insulation/.test(material)) return 'elastomer'
  return 'industrial-paint'
}

function createSurfaceDetailMaps(THREE: typeof import('three'), kind: string): SurfaceDetailMaps {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas texture generation is unavailable')
  const image = context.createImageData(size, size)
  const roughness = new Uint8Array(size * size * 4)
  const normal = new Uint8Array(size * size * 4)
  const height = new Float32Array(size * size)
  let state = Array.from(kind).reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 2166136261)
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 0x100000000
  }

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const index = y * size + x
      const broad = Math.sin(x * 0.035 + 0.8) * Math.cos(y * 0.027 + 1.6)
      const grain = random() - 0.5
      const directional = kind === 'metal' ? Math.sin(y * 0.62 + x * 0.018) : 0
      const surface = broad * 0.58 + grain * 0.42 + directional * 0.12
      height[index] = surface

      const albedoIndex = index * 4
      const value = Math.max(205, Math.min(255, Math.round(239 + surface * 18)))
      image.data[albedoIndex] = value
      image.data[albedoIndex + 1] = value
      image.data[albedoIndex + 2] = value
      image.data[albedoIndex + 3] = 255

      const roughnessValue = Math.max(150, Math.min(255, Math.round(
        (kind === 'metal' ? 204 : kind === 'elastomer' ? 232 : 221) + broad * 18 + grain * 14,
      )))
      roughness[albedoIndex] = roughnessValue
      roughness[albedoIndex + 1] = roughnessValue
      roughness[albedoIndex + 2] = roughnessValue
      roughness[albedoIndex + 3] = 255
    }
  }

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const index = y * size + x
      const left = height[y * size + Math.max(0, x - 1)]
      const right = height[y * size + Math.min(size - 1, x + 1)]
      const up = height[Math.max(0, y - 1) * size + x]
      const down = height[Math.min(size - 1, y + 1) * size + x]
      const nx = (left - right) * 0.72
      const ny = (up - down) * 0.72
      const length = Math.hypot(nx, ny, 1)
      const pixel = index * 4
      normal[pixel] = Math.round((nx / length * 0.5 + 0.5) * 255)
      normal[pixel + 1] = Math.round((ny / length * 0.5 + 0.5) * 255)
      normal[pixel + 2] = Math.round((1 / length * 0.5 + 0.5) * 255)
      normal[pixel + 3] = 255
    }
  }

  context.putImageData(image, 0, 0)
  const albedoMap = new THREE.CanvasTexture(canvas)
  albedoMap.colorSpace = THREE.SRGBColorSpace
  albedoMap.wrapS = THREE.RepeatWrapping
  albedoMap.wrapT = THREE.RepeatWrapping
  albedoMap.anisotropy = 8
  albedoMap.generateMipmaps = true
  albedoMap.minFilter = THREE.LinearMipmapLinearFilter

  const roughnessMap = new THREE.DataTexture(roughness, size, size, THREE.RGBAFormat)
  roughnessMap.wrapS = THREE.RepeatWrapping
  roughnessMap.wrapT = THREE.RepeatWrapping
  roughnessMap.generateMipmaps = true
  roughnessMap.minFilter = THREE.LinearMipmapLinearFilter
  roughnessMap.needsUpdate = true

  const normalMap = new THREE.DataTexture(normal, size, size, THREE.RGBAFormat)
  normalMap.wrapS = THREE.RepeatWrapping
  normalMap.wrapT = THREE.RepeatWrapping
  normalMap.generateMipmaps = true
  normalMap.minFilter = THREE.LinearMipmapLinearFilter
  normalMap.needsUpdate = true

  return { albedo: albedoMap, roughness: roughnessMap, normal: normalMap }
}

function setFactoryRoofVisible(root: THREE.Object3D, visible: boolean) {
  root.traverse((object) => {
    if (/^(RoofTruss|RoofPurlin|North_RingBeam|East_RingBeam)/.test(object.name)) {
      object.visible = visible
    }
  })
}

function VirtualSceneViewer({
  glbArtifact,
  cameraArtifacts,
  token,
  locale,
  productMode = false,
  advancedMode = false,
  routeWaypoints,
  routePolyline,
}: {
  glbArtifact: Artifact | undefined
  cameraArtifacts: Artifact[]
  token: string
  locale: Locale
  productMode?: boolean
  advancedMode?: boolean
  routeWaypoints?: Site['waypoints']
  routePolyline?: VirtualPose[]
}) {
  const copy = messages[locale]
  const cutawayLabel = locale === 'zh' ? '室内剖视' : 'Interior cutaway'
  const showRoofLabel = locale === 'zh' ? '显示屋顶' : 'Show roof'
  const viewportRef = useRef<HTMLDivElement>(null)
  const sceneRootRef = useRef<THREE.Object3D | null>(null)
  const cutawayModeRef = useRef(true)
  const animationActionRef = useRef<THREE.AnimationAction | null>(null)
  const animationClipDurationRef = useRef(0)
  const playingRef = useRef(false)
  const [playing, setPlaying] = useState(false)
  const [cutawayMode, setCutawayMode] = useState(true)
  const [sceneState, setSceneState] = useState<'idle' | 'loading' | 'ready' | 'error'>(glbArtifact ? 'loading' : 'idle')
  const [sceneFps, setSceneFps] = useState(0)
  const [sceneError, setSceneError] = useState('')
  const [selectedCameraName, setSelectedCameraName] = useState(cameraArtifacts[0]?.name || '')
  const [cameraUrls, setCameraUrls] = useState<Record<string, string>>({})
  const [syncState, setSyncState] = useState<SceneSyncState | null>(null)
  const cameraUrlsRef = useRef<Record<string, string>>({})
  const syncStateRef = useRef<SceneSyncState | null>(null)
  const glbArtifactId = glbArtifact?.artifact_id || ''
  const routePolylineSignature = (routePolyline || []).map((pose) => [pose.x, pose.y, pose.z || 0].join(',')).join('|')
  const routeWaypointsSignature = (routeWaypoints || []).map((waypoint) => [waypoint.waypoint_id, waypoint.position?.x, waypoint.position?.y, waypoint.position?.z || 0].join(',')).join('|')

  useEffect(() => {
    syncStateRef.current = syncState
  }, [syncState])

  useEffect(() => {
    if (!advancedMode) return
    const handleSync = (event: Event) => {
      const detail = (event as CustomEvent<SceneSyncState>).detail
      if (detail && typeof detail.frameIndex === 'number') {
        setSyncState(detail)
        setPlaying(detail.playing)
      }
    }
    window.addEventListener('inspection-sync-frame', handleSync)
    return () => window.removeEventListener('inspection-sync-frame', handleSync)
  }, [advancedMode])

  useEffect(() => {
    playingRef.current = playing
    if (animationActionRef.current) animationActionRef.current.paused = !playing
  }, [playing])

  useEffect(() => {
    cutawayModeRef.current = cutawayMode
    if (sceneRootRef.current) setFactoryRoofVisible(sceneRootRef.current, !cutawayMode)
  }, [cutawayMode])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport || !glbArtifact) return
    let disposed = false
    let cleanup: (() => void) | undefined
    const initialize = async () => {
      const [THREE, { OrbitControls }, { GLTFLoader }, { HDRLoader }] = await Promise.all([
        import('three'),
        import('three/examples/jsm/controls/OrbitControls.js'),
        import('three/examples/jsm/loaders/GLTFLoader.js'),
        import('three/examples/jsm/loaders/HDRLoader.js'),
      ])
      if (disposed) return

      let animationFrame = 0
      let viewportVisible = false
      let renderLoopActive = false
      let objectUrl = ''
      let environmentTarget: THREE.WebGLRenderTarget | null = null
      let environmentSource: THREE.DataTexture | null = null
      let pmremDisposed = false
      let inspectionOverlay: THREE.Group | null = null
      let robotMarker: THREE.Group | null = null
      const materialCache = new Map<THREE.Material, THREE.Material>()
      const originalMaterials = new Set<THREE.Material>()
      const generatedMaps = new Map<string, SurfaceDetailMaps>()
      const scene = new THREE.Scene()
      scene.background = new THREE.Color('#0B1118')
      const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 250)
      camera.up.set(0, 0, 1)
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
      // Retina capture can otherwise render the large factory scene at 2x in both
      // dimensions. Keep the physical camera view crisp while protecting the
      // shared main-thread frame budget used by the paired live feeds.
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.35))
      renderer.outputColorSpace = THREE.SRGBColorSpace
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.24
      renderer.setClearColor('#0B1118', 1)
      renderer.shadowMap.enabled = true
      renderer.shadowMap.type = THREE.PCFSoftShadowMap
      renderer.domElement.setAttribute('aria-label', copy.interactiveSceneLabel)
      viewport.appendChild(renderer.domElement)

      const controls = new OrbitControls(camera, renderer.domElement)
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.minDistance = 2
      controls.maxDistance = 90
      controls.target.set(7, 0, 1.1)

      scene.add(new THREE.HemisphereLight('#edf5ff', '#0d1722', 1.08))
      const keyLight = new THREE.DirectionalLight('#fff6e8', 3.15)
      keyLight.position.set(-10, -14, 22)
      keyLight.castShadow = true
      keyLight.shadow.mapSize.set(1024, 1024)
      keyLight.shadow.camera.near = 0.5
      keyLight.shadow.camera.far = 100
      keyLight.shadow.normalBias = 0.018
      scene.add(keyLight)
      const fillLight = new THREE.DirectionalLight('#8eb7ff', 1.08)
      fillLight.position.set(20, 10, 12)
      scene.add(fillLight)
      const rimLight = new THREE.DirectionalLight('#4ba3ff', 0.78)
      rimLight.position.set(-12, 18, 14)
      scene.add(rimLight)
      const practicalLight = new THREE.PointLight('#d9eaff', 1.35, 48, 1.5)
      practicalLight.position.set(8, -4, 9)
      scene.add(practicalLight)

      const pmremGenerator = new THREE.PMREMGenerator(renderer)
      pmremGenerator.compileEquirectangularShader()
      const disposePmrem = () => {
        if (pmremDisposed) return
        pmremDisposed = true
        pmremGenerator.dispose()
      }
      const hdriLoader = new HDRLoader().setDataType(THREE.HalfFloatType)
      void hdriLoader.loadAsync('/assets/industrial_workshop_foundry_2k.hdr').then((hdri) => {
        environmentSource = hdri
        if (disposed) {
          hdri.dispose()
          environmentSource = null
          disposePmrem()
          return
        }
        environmentTarget = pmremGenerator.fromEquirectangular(hdri)
        scene.environment = environmentTarget.texture
        scene.environmentIntensity = 0.75
        hdri.dispose()
        environmentSource = null
        disposePmrem()
      }).catch(() => disposePmrem())

      const resize = () => {
        const width = Math.max(1, viewport.clientWidth)
        const height = Math.max(1, viewport.clientHeight)
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        renderer.setSize(width, height, false)
      }
      const resizeObserver = new ResizeObserver(resize)
      resizeObserver.observe(viewport)
      resize()

      const loader = new GLTFLoader()
      const clock = new THREE.Clock()
      let fpsWindowStarted = performance.now()
      let renderedFrames = 0
      const load = async () => {
        setSceneState('loading')
        setSceneError('')
        try {
          const response = await fetch(`${apiBase}/artifacts/${glbArtifact.artifact_id}`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (!response.ok) throw new Error(`${response.status}`)
          objectUrl = URL.createObjectURL(await response.blob())
          const gltf = await loader.loadAsync(objectUrl)
          if (disposed) return
          const root = gltf.scene
          // Blender scenes are Z-up while glTF viewers conventionally use Y-up.
          // Rotate the imported root back to the factory's meter-scale Z-up frame.
          root.rotation.x = Math.PI / 2
          root.updateMatrixWorld(true)
          sceneRootRef.current = root
          setFactoryRoofVisible(root, !cutawayModeRef.current)
          root.traverse((object) => {
            const mesh = object as THREE.Mesh
            if (!mesh.isMesh) return
            if (!mesh.geometry.boundingSphere) mesh.geometry.computeBoundingSphere()
            const geometryRadius = mesh.geometry.boundingSphere?.radius ?? 0
            mesh.castShadow = object.name !== 'FactoryFloor' && geometryRadius > 0.72
            mesh.receiveShadow = object.name === 'FactoryFloor' || geometryRadius > 1.0
            const styleMaterial = (material: THREE.Material) => {
              const cached = materialCache.get(material)
              if (cached) return cached
              originalMaterials.add(material)
              const detailed = material.clone() as THREE.MeshStandardMaterial
              if (detailed.isMeshStandardMaterial) {
                const kind = surfaceKindForMaterial(material.name)
                let maps = generatedMaps.get(kind)
                if (!maps) {
                  maps = createSurfaceDetailMaps(THREE, kind)
                  generatedMaps.set(kind, maps)
                }
                detailed.map ||= maps.albedo
                detailed.roughnessMap ||= maps.roughness
                detailed.normalMap ||= maps.normal
                detailed.normalScale.set(kind === 'concrete' ? 0.22 : 0.14, kind === 'metal' ? 0.07 : 0.14)
                detailed.envMapIntensity = kind === 'metal' ? 1.28 : 0.84
                if (kind === 'metal') {
                  detailed.metalness = Math.max(detailed.metalness, 0.72)
                  detailed.roughness = Math.min(detailed.roughness, 0.38)
                } else if (kind === 'concrete') {
                  detailed.roughness = Math.max(detailed.roughness, 0.72)
                }
                detailed.needsUpdate = true
              }
              materialCache.set(material, detailed)
              return detailed
            }
            mesh.material = Array.isArray(mesh.material)
              ? mesh.material.map(styleMaterial)
              : styleMaterial(mesh.material)
          })
          scene.add(root)
          if (advancedMode) {
            inspectionOverlay = new THREE.Group()
            inspectionOverlay.name = 'InspectionRouteOverlay'
            const fallbackRoute = buildCollisionSafeRoute((routeWaypoints || []).map((waypoint) => ({
              waypoint_id: waypoint.waypoint_id,
              position: waypoint.position,
            })))
            const plannedPolyline = routePolyline?.length ? routePolyline : fallbackRoute.polyline
            const routePoints = plannedPolyline.map((pose) => ({ x: pose.x, y: pose.y, z: pose.z || 0 }))
            if (routePoints.length > 1) {
              const routeVectors = routePoints.map((point) => new THREE.Vector3(point.x, point.y, 0.1))
              const routeGeometry = new THREE.BufferGeometry().setFromPoints(routeVectors)
              const routeMaterial = new THREE.LineBasicMaterial({ color: '#3d8dff', transparent: true, opacity: 0.48 })
              inspectionOverlay.add(new THREE.Line(routeGeometry, routeMaterial))
              const routePath = new THREE.CurvePath<THREE.Vector3>()
              routeVectors.slice(1).forEach((point, index) => routePath.add(new THREE.LineCurve3(routeVectors[index], point)))
              const corridorGeometry = new THREE.TubeGeometry(routePath, Math.max(24, routeVectors.length * 8), 0.045, 8, false)
              const corridorMaterial = new THREE.MeshStandardMaterial({
                color: '#1677ff', emissive: '#003b9a', emissiveIntensity: 0.78,
                roughness: 0.42, metalness: 0.12, transparent: true, opacity: 0.92,
              })
              inspectionOverlay.add(new THREE.Mesh(corridorGeometry, corridorMaterial))
            }
            robotMarker = new THREE.Group()
            robotMarker.name = 'InspectionRobotMarker'
            const markerMaterial = new THREE.MeshStandardMaterial({
              color: '#2f8cff', emissive: '#003b9a', emissiveIntensity: 0.82, roughness: 0.32, metalness: 0.28,
            })
            const marker = new THREE.Mesh(new THREE.SphereGeometry(0.22, 20, 12), markerMaterial)
            marker.castShadow = true
            const markerRing = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.035, 8, 32), new THREE.MeshBasicMaterial({ color: '#70b2ff', transparent: true, opacity: 0.9 }))
            markerRing.rotation.x = Math.PI / 2
            const markerHeading = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.34, 12), new THREE.MeshBasicMaterial({ color: '#e7f1ff' }))
            markerHeading.rotation.y = Math.PI / 2
            markerHeading.position.x = 0.25
            robotMarker.add(marker, markerRing, markerHeading)
            inspectionOverlay.add(robotMarker)
            scene.add(inspectionOverlay)
          }
          const bounds = new THREE.Box3().setFromObject(root)
          const center = bounds.getCenter(new THREE.Vector3())
          const size = bounds.getSize(new THREE.Vector3())
          const maxDimension = Math.max(size.x, size.y, size.z, 1)
          controls.target.copy(center)
          controls.target.z -= size.z * 0.10
          const shadowCamera = keyLight.shadow.camera as THREE.OrthographicCamera
          shadowCamera.left = -maxDimension * 0.62
          shadowCamera.right = maxDimension * 0.62
          shadowCamera.top = maxDimension * 0.62
          shadowCamera.bottom = -maxDimension * 0.62
          shadowCamera.updateProjectionMatrix()
          camera.position.set(center.x + maxDimension * 0.46, center.y - maxDimension * 0.58, center.z + maxDimension * 0.22)
          camera.near = Math.max(0.03, maxDimension / 300)
          camera.far = maxDimension * 8
          camera.updateProjectionMatrix()
          if (gltf.animations.length) {
            const mixer = new THREE.AnimationMixer(root)
            const action = mixer.clipAction(gltf.animations[0])
            action.play()
            action.paused = !playingRef.current
            animationClipDurationRef.current = gltf.animations[0].duration
            animationActionRef.current = action
            ;(renderer as THREE.WebGLRenderer & { __inspectionMixer?: THREE.AnimationMixer }).__inspectionMixer = mixer
          }
          setSceneState('ready')
        } catch (error) {
          if (!disposed) {
            setSceneState('error')
            setSceneError(error instanceof Error ? error.message : String(error))
          }
        }
      }
      void load()

      const render = () => {
        if (disposed || !viewportVisible) {
          renderLoopActive = false
          return
        }
        animationFrame = requestAnimationFrame(render)
        renderedFrames += 1
        const now = performance.now()
        if (now - fpsWindowStarted >= 750) {
          setSceneFps(Math.round(renderedFrames * 1000 / (now - fpsWindowStarted)))
          fpsWindowStarted = now
          renderedFrames = 0
        }
        const delta = Math.min(clock.getDelta(), 0.08)
        const mixer = (renderer as THREE.WebGLRenderer & { __inspectionMixer?: THREE.AnimationMixer }).__inspectionMixer
        const sync = syncStateRef.current
        if (mixer && sync && animationActionRef.current && animationClipDurationRef.current > 0) {
          const syncFrameIndex = sync.streamFrameIndex ?? sync.frameIndex
          const syncFrameCount = sync.streamFrameCount ?? 0
          const normalized = syncFrameCount > 1
            ? THREE.MathUtils.clamp(syncFrameIndex / (syncFrameCount - 1), 0, 1)
            : 0
          animationActionRef.current.paused = false
          mixer.setTime(animationClipDurationRef.current * normalized)
          animationActionRef.current.paused = true
        } else if (mixer && playingRef.current) {
          mixer.update(delta)
        }
        if (robotMarker && syncStateRef.current) {
          const pose = syncStateRef.current.pose
          robotMarker.visible = true
          robotMarker.position.set(pose.x, pose.y, (pose.z || 0) + 0.28)
          robotMarker.rotation.z = THREE.MathUtils.degToRad(-(pose.yaw_deg || 0))
        }
        controls.update()
        renderer.render(scene, camera)
      }
      const visibilityObserver = new IntersectionObserver((entries) => {
        const isVisible = entries.some((entry) => entry.isIntersecting)
        if (isVisible === viewportVisible) return
        viewportVisible = isVisible
        if (isVisible && !renderLoopActive) {
          renderLoopActive = true
          render()
        } else if (!isVisible) {
          cancelAnimationFrame(animationFrame)
          renderLoopActive = false
        }
      }, { rootMargin: '96px' })
      visibilityObserver.observe(viewport)
      return () => {
        cancelAnimationFrame(animationFrame)
        visibilityObserver.disconnect()
        resizeObserver.disconnect()
        controls.dispose()
        disposePmrem()
        environmentTarget?.dispose()
        environmentSource?.dispose()
        renderer.dispose()
        scene.traverse((object) => {
          const mesh = object as THREE.Mesh
          if (mesh.geometry) mesh.geometry.dispose()
          if (Array.isArray(mesh.material)) mesh.material.forEach((material) => material.dispose())
          else if (mesh.material) mesh.material.dispose()
        })
        originalMaterials.forEach((material) => material.dispose())
        generatedMaps.forEach((maps) => {
          maps.albedo.dispose()
          maps.roughness.dispose()
          maps.normal.dispose()
        })
        animationActionRef.current = null
        animationClipDurationRef.current = 0
        sceneRootRef.current = null
        if (objectUrl) URL.revokeObjectURL(objectUrl)
        renderer.domElement.remove()
      }
    }
    void initialize().then((dispose) => {
      if (disposed) dispose?.()
      else cleanup = dispose
    }).catch((error: unknown) => {
      if (disposed) return
      setSceneState('error')
      setSceneError(error instanceof Error ? error.message : String(error))
    })
    return () => {
      disposed = true
      cleanup?.()
    }
  }, [advancedMode, glbArtifactId, routePolylineSignature, routeWaypointsSignature, token])

  useEffect(() => {
    if (!selectedCameraName || cameraUrls[selectedCameraName] || !token) return
    const artifact = cameraArtifacts.find((item) => item.name === selectedCameraName)
    if (!artifact) return
    let active = true
    void fetch(`${apiBase}/artifacts/${artifact.artifact_id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`${response.status}`)
      return URL.createObjectURL(await response.blob())
    }).then((url) => {
      if (!active) {
        URL.revokeObjectURL(url)
        return
      }
      cameraUrlsRef.current[artifact.name] = url
      setCameraUrls((current) => ({ ...current, [artifact.name]: url }))
    }).catch(() => undefined)
    return () => { active = false }
  }, [cameraArtifacts, cameraUrls, selectedCameraName, token])

  useEffect(() => () => {
    Object.values(cameraUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
  }, [])

  if (!glbArtifact) return <section className="virtual-scene-viewer"><div className="empty-inline"><Box size={17} />{copy.virtualSceneUnavailable}</div></section>
  const selectedCamera = cameraArtifacts.find((item) => item.name === selectedCameraName)
  const selectedCameraUrl = selectedCamera ? cameraUrls[selectedCamera.name] : undefined
  const cameraGroups: CameraGroupKey[] = ['overview', 'cctv', 'robot', 'orbit', 'detail', 'other']
  const groupedCameras = cameraGroups.map((group) => ({
    group,
    artifacts: cameraArtifacts.filter((artifact) => cameraGroupForName(artifact.name) === group),
  })).filter(({ artifacts }) => artifacts.length > 0)
  const osdFrameIndex = syncState?.streamFrameIndex ?? syncState?.frameIndex
  const osdTimecode = syncState?.timecode || 'TC --:--:--:--'
  const osdCameraCode = selectedCameraName
    ? cameraGroupForName(selectedCameraName) === 'overview'
      ? 'CAM-OVERVIEW'
      : cameraGroupForName(selectedCameraName) === 'cctv'
        ? 'CAM-CCTV'
        : cameraGroupForName(selectedCameraName) === 'robot'
          ? 'CAM-ROBOT'
          : cameraGroupForName(selectedCameraName) === 'detail'
            ? 'CAM-DETAIL'
            : 'CAM-ORBIT'
    : 'CAM-ROBOT'
  return <section className="virtual-scene-viewer">
    <div className="detail-section-heading scene-viewer-heading">
      <div><h3>{copy.virtualSceneViewer}</h3><p>{copy.virtualSceneDescription}</p></div>
      <div className="scene-viewer-actions">
        {productMode && <span className="scene-version-chip"><BadgeCheck size={12} />{advancedMode ? copy.v34Workbench : copy.v33Workbench}</span>}
        <button type="button" className="secondary-button" data-cutaway-active={cutawayMode} aria-pressed={cutawayMode} onClick={() => setCutawayMode((current) => !current)} title={cutawayMode ? showRoofLabel : cutawayLabel}><span aria-hidden="true">{cutawayMode ? <Eye size={14} /> : <EyeOff size={14} />}</span>{cutawayMode ? showRoofLabel : cutawayLabel}</button>
        <button type="button" className="secondary-button" onClick={() => window.dispatchEvent(new CustomEvent<InspectionSyncCommand>('inspection-sync-command', { detail: { type: 'toggle' } }))} title={playing ? copy.pauseRobot : copy.playRobot}><span aria-hidden="true">{playing ? <Pause size={14} /> : <Play size={14} />}</span>{playing ? copy.pauseRobot : copy.playRobot}</button>
      </div>
    </div>
    <div className="scene-viewer-layout">
      <div className="scene-viewport" ref={viewportRef} data-scene-overlay={advancedMode ? 'active' : 'disabled'} data-scene-state={sceneState} data-sync-frame={syncState ? syncState.frameIndex : undefined}>
        {sceneState === 'loading' && <div className="scene-viewport-state"><Rotate3d size={18} />{copy.virtualSceneLoading}</div>}
        {sceneState === 'error' && <div className="scene-viewport-state scene-viewport-error"><Box size={18} /><span>{copy.virtualSceneLoadFailed}<small>{sceneError}</small></span></div>}
        {advancedMode && <div className="scene-telemetry-overlay scene-osd" aria-label={copy.sceneTwinLayer}>
          <span className="scene-osd-corner scene-osd-corner-tl" aria-hidden="true" />
          <span className="scene-osd-corner scene-osd-corner-tr" aria-hidden="true" />
          <span className="scene-osd-corner scene-osd-corner-bl" aria-hidden="true" />
          <span className="scene-osd-corner scene-osd-corner-br" aria-hidden="true" />
          <div className="scene-osd-header">
            <span><i className={syncState ? 'live-dot active' : 'live-dot'} />{locale === 'zh' ? '3D 孪生视图' : '3D TWIN VIEW'}</span>
            <strong>{syncState && typeof osdFrameIndex === 'number'
              ? `F${String(osdFrameIndex + 1).padStart(3, '0')}${syncState.streamFrameCount ? ` / ${String(syncState.streamFrameCount).padStart(3, '0')}` : ''}`
              : 'SYNC WAIT'}</strong>
          </div>
          <div className="scene-osd-meta" aria-label={copy.sceneTwinLayer}>
            <span><small>{copy.timecode}</small><strong>{osdTimecode}</strong></span>
            <span><small>{copy.cameraCode}</small><strong>{osdCameraCode}</strong></span>
            <span><small>{copy.renderBackend}</small><strong>THREE.JS / WEBGL</strong></span>
            <span><small>{copy.framesPerSecond}</small><strong>{sceneFps || '—'} FPS</strong></span>
          </div>
          <div className="scene-osd-reticle" aria-hidden="true"><span /><span /></div>
          <div className="scene-osd-readouts">
            <span><small>{locale === 'zh' ? '位置 X' : 'POS X'}</small><strong>{syncState ? `${syncState.pose.x.toFixed(2)} m` : '—'}</strong></span>
            <span><small>{locale === 'zh' ? '位置 Y' : 'POS Y'}</small><strong>{syncState ? `${syncState.pose.y.toFixed(2)} m` : '—'}</strong></span>
            <span><small>{locale === 'zh' ? '朝向' : 'YAW'}</small><strong>{syncState ? `${(syncState.pose.yaw_deg || 0).toFixed(0)}°` : '—'}</strong></span>
          </div>
          <div className="scene-osd-footer"><span>{copy.sceneTwinLayer}</span><span>{syncState?.waypointId || '—'}</span><span>{syncState ? `R${String(syncState.routeFrame).padStart(3, '0')}` : 'R---'}</span></div>
        </div>}
      </div>
      <aside className="scene-camera-rail">
        <div className="scene-camera-rail-heading"><span><Camera size={14} />{copy.cameraViews}</span><small>{cameraArtifacts.length} {copy.cameraViewCount}</small></div>
        <div className="scene-camera-list">{groupedCameras.map(({ group, artifacts }) => <div className="scene-camera-group" key={group}>
          {productMode && <div className="scene-camera-group-heading"><span>{cameraGroupLabel(group, locale)}</span><small>{artifacts.length}</small></div>}
          {artifacts.map((artifact) => <button type="button" className={`scene-camera-button${artifact.name === selectedCameraName ? ' selected' : ''}`} key={artifact.artifact_id} onClick={() => setSelectedCameraName(artifact.name)}><span className="scene-camera-icon"><Camera size={13} /></span><span>{virtualCameraLabel(artifact.name, locale)}</span></button>)}
        </div>)}</div>
        <div className="scene-camera-preview">{selectedCameraUrl ? <img src={selectedCameraUrl} alt={selectedCamera ? virtualCameraLabel(selectedCamera.name, locale) : ''} /> : <span><Camera size={17} />{copy.cameraLoading}</span>}</div>
        {selectedCamera && <div className="scene-camera-selection">
          <span><small>{copy.sceneCurrentCamera}</small><strong>{virtualCameraLabel(selectedCamera.name, locale)}</strong></span>
          <span><small>{copy.sceneSource}</small><strong>{sourceLabel(selectedCamera.source, locale)}</strong></span>
        </div>}
      </aside>
    </div>
    {productMode && selectedCamera && <div className="scene-integrity-strip">
      <span><Layers3 size={13} /><small>{copy.sceneCurrentCamera}</small><strong>{virtualCameraLabel(selectedCamera.name, locale)}</strong></span>
      <span><Hash size={13} /><small>{copy.sceneHash}</small><strong title={selectedCamera.sha256}>{selectedCamera.sha256.slice(0, 16)}…</strong></span>
      <span><ShieldCheck size={13} /><small>{copy.sceneIntegrity}</small><strong>{copy.verified}</strong></span>
      <span><Box size={13} /><small>{copy.sceneSource}</small><strong>{sourceLabel(selectedCamera.source, locale)}</strong></span>
    </div>}
    {advancedMode && <div className="scene-telemetry-strip">
      <span><Activity size={13} /><small>{copy.sceneTelemetry}</small><strong>{syncState ? copy.sceneSynced : copy.sceneWaitingSync}</strong></span>
      <span><MapPin size={13} /><small>{copy.waypoint}</small><strong>{syncState?.waypointId || '—'}{syncState?.deviceName ? ` · ${deviceLabel(syncState.deviceName, locale)}` : ''}</strong></span>
      <span><Route size={13} /><small>{copy.sceneRouteIndex}</small><strong>{syncState ? `#${String(syncState.routeFrame).padStart(3, '0')}` : '—'}</strong></span>
      <span><Video size={13} /><small>{copy.sceneRenderFrame}</small><strong>{syncState ? `#${String(syncState.renderFrame).padStart(4, '0')}` : '—'}</strong></span>
      <span><Rotate3d size={13} /><small>{copy.scenePose}</small><strong>{syncState ? `${syncState.pose.x.toFixed(2)}, ${syncState.pose.y.toFixed(2)} m` : '—'}</strong></span>
    </div>}
    <div className="scene-viewer-footer"><span><Box size={13} />{copy.sceneSyntheticLocal}</span><span>{copy.sceneSyntheticBoundary}</span></div>
  </section>
}

function replayClock(seconds: number) {
  const safeSeconds = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(safeSeconds / 60).toString().padStart(2, '0')
  const remainder = (safeSeconds % 60).toString().padStart(2, '0')
  return `${minutes}:${remainder}`
}

function replayTimecode(seconds: number, fps: number) {
  const time = Math.max(0, seconds)
  const whole = Math.floor(time)
  const fields = [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60,
    Math.min(Math.ceil(fps) - 1, Math.floor((time - whole) * fps))]
  return `TC ${fields.map((value) => String(value).padStart(2, '0')).join(':')}`
}

function RealtimeCameraFeed({
  primaryUrl,
  nextUrl,
  alt,
  cameraKind,
  locale,
  playing,
  transitionMs,
  frameLabel,
  sourceLabel,
}: RealtimeCameraFeedProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const primaryUrlRef = useRef(primaryUrl)
  const nextUrlRef = useRef(nextUrl)
  const playingRef = useRef(playing)
  const transitionStartRef = useRef(performance.now())
  const frameCounterRef = useRef({ last: performance.now(), frames: 0, fps: 0 })
  const imageCacheRef = useRef(new Map<string, HTMLImageElement>())
  const [renderState, setRenderState] = useState({ backend: 'WEBGL', fps: 0, ready: false })

  useEffect(() => {
    playingRef.current = playing
  }, [playing])

  useEffect(() => {
    if (primaryUrlRef.current !== primaryUrl) {
      primaryUrlRef.current = primaryUrl
      transitionStartRef.current = performance.now()
    }
    nextUrlRef.current = nextUrl
  }, [nextUrl, primaryUrl])

  useEffect(() => {
    let active = true
    const urls = [primaryUrl, nextUrl].filter((url): url is string => Boolean(url))
    urls.forEach((url) => {
      if (imageCacheRef.current.has(url)) return
      const image = new Image()
      image.decoding = 'async'
      image.onload = () => {
        if (active) setRenderState((current) => ({ ...current, ready: true }))
      }
      image.src = url
      imageCacheRef.current.set(url, image)
    })
    return () => { active = false }
  }, [nextUrl, primaryUrl])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let disposed = false
    let animationFrame = 0
    let gl: WebGLRenderingContext | null = null
    let backend = 'CANVAS'
    try {
      gl = canvas.getContext('webgl', { alpha: false, antialias: true, powerPreference: 'high-performance' })
    } catch {
      gl = null
    }

    const drawFallback = (context: CanvasRenderingContext2D, now: number) => {
      const currentImage = primaryUrlRef.current ? imageCacheRef.current.get(primaryUrlRef.current) : undefined
      const nextImage = nextUrlRef.current ? imageCacheRef.current.get(nextUrlRef.current) : undefined
      if (!currentImage?.complete || !currentImage.naturalWidth) return
      const width = canvas.width
      const height = canvas.height
      const drawCover = (image: HTMLImageElement, alpha: number) => {
        const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight)
        const drawWidth = image.naturalWidth * scale
        const drawHeight = image.naturalHeight * scale
        context.globalAlpha = alpha
        context.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight)
      }
      const elapsed = Math.max(0, now - transitionStartRef.current)
      const blend = nextImage && nextImage.complete && nextImage.naturalWidth
        ? Math.min(1, elapsed / Math.max(160, transitionMs))
        : 0
      context.clearRect(0, 0, width, height)
      drawCover(currentImage, 1 - blend)
      if (blend > 0) drawCover(nextImage!, blend)
      context.globalAlpha = 1
      context.fillStyle = 'rgba(8, 15, 24, .07)'
      for (let y = 0; y < height; y += 4) context.fillRect(0, y, width, 1)
    }

    if (!gl) {
      const context = canvas.getContext('2d')
      if (!context) return
      backend = 'CANVAS'
      const resize = () => {
        const rect = canvas.getBoundingClientRect()
        const ratio = Math.min(window.devicePixelRatio || 1, 2)
        canvas.width = Math.max(1, Math.round(rect.width * ratio))
        canvas.height = Math.max(1, Math.round(rect.height * ratio))
      }
      const resizeObserver = new ResizeObserver(resize)
      resizeObserver.observe(canvas)
      resize()
      const render = (now: number) => {
        if (disposed) return
        animationFrame = requestAnimationFrame(render)
        drawFallback(context, now)
        const counter = frameCounterRef.current
        counter.frames += 1
        if (now - counter.last > 500) {
          const fps = Math.round(counter.frames * 1000 / (now - counter.last))
          counter.last = now
          counter.frames = 0
          setRenderState((current) => ({ ...current, backend, fps }))
        }
      }
      animationFrame = requestAnimationFrame(render)
      return () => {
        disposed = true
        cancelAnimationFrame(animationFrame)
        resizeObserver.disconnect()
      }
    }

    backend = 'WEBGL GPU'
    const vertexShader = gl.createShader(gl.VERTEX_SHADER)
    const fragmentShader = gl.createShader(gl.FRAGMENT_SHADER)
    if (!vertexShader || !fragmentShader) return
    gl.shaderSource(vertexShader, `
      attribute vec2 aPosition;
      varying vec2 vUv;
      void main() {
        vUv = aPosition * 0.5 + 0.5;
        gl_Position = vec4(aPosition, 0.0, 1.0);
      }
    `)
    gl.shaderSource(fragmentShader, `
      precision highp float;
      uniform sampler2D uCurrent;
      uniform sampler2D uNext;
      uniform float uBlend;
      uniform float uTime;
      uniform float uCameraKind;
      uniform vec2 uResolution;
      varying vec2 vUv;

      vec2 coverUv(vec2 uv, vec2 sourceAspect) {
        float canvasAspect = uResolution.x / max(uResolution.y, 1.0);
        float imageAspect = sourceAspect.x / max(sourceAspect.y, 1.0);
        if (canvasAspect > imageAspect) {
          uv.y = (uv.y - 0.5) * canvasAspect / imageAspect + 0.5;
        } else {
          uv.x = (uv.x - 0.5) * imageAspect / canvasAspect + 0.5;
        }
        return uv;
      }

      void main() {
        float motion = uCameraKind < 0.5 ? 1.0 : 0.22;
        vec2 drift = vec2(
          sin(uTime * 0.73) * 0.0024 * motion,
          cos(uTime * 0.51) * 0.0017 * motion
        );
        vec2 uv = coverUv(vUv + drift, vec2(16.0, 9.0));
        vec2 nextUv = coverUv(vUv + drift + vec2(0.004 * (uBlend - 0.5) * motion, 0.0), vec2(16.0, 9.0));
        vec4 currentColor = texture2D(uCurrent, clamp(uv, 0.001, 0.999));
        vec4 nextColor = texture2D(uNext, clamp(nextUv, 0.001, 0.999));
        float blend = smoothstep(0.0, 1.0, uBlend);
        vec3 color = mix(currentColor.rgb, nextColor.rgb, blend);
        float scanline = sin(vUv.y * uResolution.y * 0.42) * 0.012;
        float vignette = smoothstep(0.88, 0.28, distance(vUv, vec2(0.5)));
        float noise = fract(sin(dot(vUv * uResolution + uTime, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
        color += scanline + noise * 0.006;
        color *= 1.0 - vignette * 0.085;
        gl_FragColor = vec4(color, 1.0);
      }
    `)
    gl.compileShader(vertexShader)
    gl.compileShader(fragmentShader)
    const program = gl.createProgram()
    if (!program) return
    gl.attachShader(program, vertexShader)
    gl.attachShader(program, fragmentShader)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return
    gl.useProgram(program)

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
    const position = gl.getAttribLocation(program, 'aPosition')
    gl.enableVertexAttribArray(position)
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0)
    const currentTexture = gl.createTexture()
    const nextTexture = gl.createTexture()
    if (!currentTexture || !nextTexture) return
    const configureTexture = (texture: WebGLTexture, image?: HTMLImageElement) => {
      gl!.bindTexture(gl!.TEXTURE_2D, texture)
      gl!.pixelStorei(gl!.UNPACK_FLIP_Y_WEBGL, 1)
      gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE)
      gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE)
      gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.LINEAR)
      gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.LINEAR)
      if (image?.complete && image.naturalWidth) gl!.texImage2D(gl!.TEXTURE_2D, 0, gl!.RGBA, gl!.RGBA, gl!.UNSIGNED_BYTE, image)
      else gl!.texImage2D(gl!.TEXTURE_2D, 0, gl!.RGBA, 1, 1, 0, gl!.RGBA, gl!.UNSIGNED_BYTE, new Uint8Array([24, 34, 46, 255]))
    }
    configureTexture(currentTexture)
    configureTexture(nextTexture)
    const currentLocation = gl.getUniformLocation(program, 'uCurrent')
    const nextLocation = gl.getUniformLocation(program, 'uNext')
    const blendLocation = gl.getUniformLocation(program, 'uBlend')
    const timeLocation = gl.getUniformLocation(program, 'uTime')
    const cameraLocation = gl.getUniformLocation(program, 'uCameraKind')
    const resolutionLocation = gl.getUniformLocation(program, 'uResolution')
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.round(rect.width * ratio))
      canvas.height = Math.max(1, Math.round(rect.height * ratio))
      gl!.viewport(0, 0, canvas.width, canvas.height)
    }
    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvas)
    resize()
    let uploadedPrimary = ''
    let uploadedNext = ''
    const render = (now: number) => {
      if (disposed) return
      animationFrame = requestAnimationFrame(render)
      const currentUrl = primaryUrlRef.current || ''
      const upcomingUrl = nextUrlRef.current || currentUrl
      const currentImage = currentUrl ? imageCacheRef.current.get(currentUrl) : undefined
      const nextImage = upcomingUrl ? imageCacheRef.current.get(upcomingUrl) : undefined
      if (currentImage?.complete && currentImage.naturalWidth && currentUrl !== uploadedPrimary) {
        gl!.activeTexture(gl!.TEXTURE0)
        configureTexture(currentTexture, currentImage)
        uploadedPrimary = currentUrl
      }
      if (nextImage?.complete && nextImage.naturalWidth && upcomingUrl !== uploadedNext) {
        gl!.activeTexture(gl!.TEXTURE1)
        configureTexture(nextTexture, nextImage)
        uploadedNext = upcomingUrl
      }
      const blend = nextImage?.complete && nextImage.naturalWidth && upcomingUrl !== currentUrl
        ? Math.min(1, Math.max(0, (now - transitionStartRef.current) / Math.max(160, transitionMs)))
        : 0
      gl!.activeTexture(gl!.TEXTURE0)
      gl!.bindTexture(gl!.TEXTURE_2D, currentTexture)
      gl!.activeTexture(gl!.TEXTURE1)
      gl!.bindTexture(gl!.TEXTURE_2D, nextTexture)
      gl!.uniform1i(currentLocation, 0)
      gl!.uniform1i(nextLocation, 1)
      gl!.uniform1f(blendLocation, blend)
      gl!.uniform1f(timeLocation, now / 1000)
      gl!.uniform1f(cameraLocation, cameraKind === 'robot' ? 0 : 1)
      gl!.uniform2f(resolutionLocation, canvas.width, canvas.height)
      gl!.drawArrays(gl!.TRIANGLE_STRIP, 0, 4)
      const counter = frameCounterRef.current
      counter.frames += 1
      if (now - counter.last > 500) {
        const fps = Math.round(counter.frames * 1000 / (now - counter.last))
        counter.last = now
        counter.frames = 0
        setRenderState((current) => ({ ...current, backend, fps, ready: Boolean(currentImage?.complete && currentImage.naturalWidth) }))
      }
    }
    animationFrame = requestAnimationFrame(render)
    return () => {
      disposed = true
      cancelAnimationFrame(animationFrame)
      resizeObserver.disconnect()
      gl!.deleteTexture(currentTexture)
      gl!.deleteTexture(nextTexture)
      gl!.deleteBuffer(buffer)
      gl!.deleteProgram(program)
      gl!.deleteShader(vertexShader)
      gl!.deleteShader(fragmentShader)
    }
  }, [cameraKind, transitionMs])

  const liveLabel = locale === 'zh' ? '实时合成' : 'LIVE SYNTHETIC'
  const backendLabel = locale === 'zh' ? 'WebGL GPU' : 'WEBGL GPU'
  return <div className="realtime-camera-feed" role="img" aria-label={alt}>
    {primaryUrl && <img className="realtime-camera-still" src={primaryUrl} alt="" aria-hidden="true" />}
    <canvas className={renderState.ready ? 'is-ready' : ''} ref={canvasRef} aria-hidden="true" />
    <div className="realtime-camera-osd realtime-camera-osd-top">
      <span><i className={renderState.ready ? 'is-live' : ''} />{liveLabel}</span>
      <strong>{renderState.backend === 'WEBGL GPU' ? backendLabel : 'CANVAS'}</strong>
    </div>
    <div className="realtime-camera-osd realtime-camera-osd-bottom">
      <span>{sourceLabel}</span>
      <strong>{frameLabel}</strong>
      <b>{renderState.fps || 0} FPS</b>
    </div>
  </div>
}

function ContinuousVideoFeed({
  src,
  posterUrl,
  videoRef,
  alt,
  cameraKind,
  locale,
  playing,
  playbackRate,
  fpsHint,
  frameLabel,
  sourceLabel,
  onFrame,
  onEnded,
  onReady,
}: ContinuousVideoFeedProps) {
  const [renderState, setRenderState] = useState({ fps: fpsHint || 0, ready: false, error: false })
  const readyFrameRef = useRef(false)
  const readyFallbackTimerRef = useRef<number | null>(null)

  const markDecodedFrameReady = useCallback(() => {
    if (readyFrameRef.current) return
    readyFrameRef.current = true
    if (readyFallbackTimerRef.current !== null) {
      window.clearTimeout(readyFallbackTimerRef.current)
      readyFallbackTimerRef.current = null
    }
    setRenderState((current) => ({ ...current, ready: true, error: false }))
    onReady?.()
  }, [onReady])

  const armDecodedFrameReady = useCallback(() => {
    const video = videoRef.current
    if (!video || readyFrameRef.current || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return

    // loadeddata/canplay can arrive before Chrome has presented the first decoded
    // frame. Prefer a video-frame callback and keep the poster visible until then.
    if ('requestVideoFrameCallback' in video) {
      video.requestVideoFrameCallback(() => markDecodedFrameReady())
    }
    if (readyFallbackTimerRef.current === null) {
      readyFallbackTimerRef.current = window.setTimeout(() => {
        readyFallbackTimerRef.current = null
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) markDecodedFrameReady()
      }, 240)
    }
  }, [markDecodedFrameReady, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    readyFrameRef.current = false
    if (readyFallbackTimerRef.current !== null) {
      window.clearTimeout(readyFallbackTimerRef.current)
      readyFallbackTimerRef.current = null
    }
    if (!src) {
      video.removeAttribute('src')
      video.load()
      setRenderState({ fps: 0, ready: false, error: false })
      return
    }
    video.load()
    setRenderState((current) => ({ ...current, fps: fpsHint || current.fps || 0, ready: false, error: false }))
    return () => {
      if (readyFallbackTimerRef.current !== null) {
        window.clearTimeout(readyFallbackTimerRef.current)
        readyFallbackTimerRef.current = null
      }
    }
  }, [fpsHint, src, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    // Changing speed must not reload the media element. Reloading here drops
    // the decoder's buffered frames and is visible as a hitch in the replay.
    video.playbackRate = playbackRate
  }, [playbackRate, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !src) return
    video.playbackRate = playbackRate
    if (playing) {
      void video.play().catch(() => undefined)
    } else {
      video.pause()
    }
  }, [playbackRate, playing, src, videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !src) return
    let active = true
    let animationFrame = 0
    let videoCallback = 0
    let fallbackFrames = 0
    let lastSampleAt = performance.now()
    let lastTotalFrames = video.getVideoPlaybackQuality().totalVideoFrames
    let lastDroppedFrames = video.getVideoPlaybackQuality().droppedVideoFrames
    const reportFrame = (seconds: number) => {
      if (!active) return
      onFrame?.(seconds)
      fallbackFrames += 1
    }
    const fpsInterval = window.setInterval(() => {
      const now = performance.now()
      const quality = video.getVideoPlaybackQuality()
      const elapsed = now - lastSampleAt
      const submittedFrames = quality.totalVideoFrames - lastTotalFrames
      const droppedFrames = quality.droppedVideoFrames - lastDroppedFrames
      const presentedFrames = Math.max(0, submittedFrames - droppedFrames)
      const measuredFps = Math.round((presentedFrames || (submittedFrames === 0 ? fallbackFrames : 0)) * 1000 / elapsed)
      const fps = measuredFps || fpsHint || 0
      fallbackFrames = 0
      lastSampleAt = now
      lastTotalFrames = quality.totalVideoFrames
      lastDroppedFrames = quality.droppedVideoFrames
      setRenderState((current) => ({ ...current, fps }))
    }, 500)
    const schedule = () => {
      if (!active) return
      if ('requestVideoFrameCallback' in video) {
        videoCallback = video.requestVideoFrameCallback((_now, metadata) => {
          reportFrame(metadata.mediaTime)
          schedule()
        })
      } else {
        animationFrame = requestAnimationFrame(() => {
          reportFrame((video as HTMLVideoElement).currentTime)
          schedule()
        })
      }
    }
    schedule()
    return () => {
      active = false
      window.clearInterval(fpsInterval)
      if (videoCallback && 'cancelVideoFrameCallback' in video) video.cancelVideoFrameCallback(videoCallback)
      cancelAnimationFrame(animationFrame)
    }
  }, [fpsHint, onFrame, src, videoRef])

  const liveLabel = locale === 'zh' ? '实时视频' : 'LIVE VIDEO'
  const sourceTag = cameraKind === 'robot'
    ? (locale === 'zh' ? 'BLENDER / ROBOT RGB' : 'BLENDER / ROBOT RGB')
    : (locale === 'zh' ? 'BLENDER / WAREHOUSE CCTV' : 'BLENDER / WAREHOUSE CCTV')
  return <div className={`realtime-camera-feed continuous-video-feed${renderState.ready && !renderState.error ? ' is-video-ready' : ''}`} role="img" aria-label={alt}>
    {posterUrl && <img className="realtime-camera-still" src={posterUrl} alt="" aria-hidden="true" />}
    <video
      ref={videoRef}
      src={src}
      poster={posterUrl}
      className={renderState.ready && !renderState.error ? 'is-ready' : ''}
      muted
      playsInline
      preload="auto"
      disablePictureInPicture
      onLoadedData={() => {
        armDecodedFrameReady()
        if (playing) void videoRef.current?.play().catch(() => undefined)
      }}
      onCanPlay={() => {
        armDecodedFrameReady()
        if (playing) void videoRef.current?.play().catch(() => undefined)
      }}
      onPlaying={() => markDecodedFrameReady()}
      onError={() => {
        readyFrameRef.current = false
        setRenderState((current) => ({ ...current, ready: false, error: true }))
      }}
      onEnded={onEnded}
      aria-label={alt}
    />
    <div className="realtime-camera-osd realtime-camera-osd-top">
      <span><i className={renderState.ready && !renderState.error ? 'is-live' : ''} />{liveLabel}</span>
      <strong>{sourceTag}</strong>
    </div>
    {!renderState.ready && <div className="realtime-camera-stream-state" aria-live="polite">
      {renderState.error ? (locale === 'zh' ? '连续视频流不可用，保留同步海报' : 'Continuous stream unavailable; showing sync poster') : (locale === 'zh' ? '正在缓冲连续视频流' : 'BUFFERING CONTINUOUS STREAM')}
    </div>}
    <div className="realtime-camera-osd realtime-camera-osd-bottom">
      <span>{sourceLabel}</span>
      <strong>{frameLabel}</strong>
      <b>{renderState.fps || fpsHint || 0} FPS</b>
    </div>
  </div>
}

function SynchronizedInspectionReplay({
  missionDetail,
  missionArtifacts,
  token,
  locale,
  site,
  productMode = false,
}: {
  missionDetail: MissionDetail
  missionArtifacts: Artifact[]
  token: string
  locale: Locale
  site: Site | null
  productMode?: boolean
}) {
  const copy = messages[locale]
  const sceneInputArtifact = missionArtifacts.find((artifact) => artifact.name === 'scene_input.json')
  const trajectoryArtifact = missionArtifacts.find((artifact) => artifact.name === 'trajectory.json')
  const continuousManifestArtifact = missionArtifacts.find((artifact) => artifact.name === 'continuous_video_manifest.json')
  const streamManifestArtifact = continuousManifestArtifact
    || missionArtifacts.find((artifact) => artifact.name === 'synchronized_video_manifest.json')
  const robotArtifacts = missionArtifacts.filter((artifact) => artifact.name.startsWith('virtual_world__') && artifact.name.endsWith('__rgb_camera.png'))
  const warehouseCctvArtifacts = missionArtifacts.filter((artifact) => artifact.name.startsWith('factory_cctv__')
    && artifact.name.endsWith('.png'))
  const fixedCameraArtifacts = warehouseCctvArtifacts.length ? warehouseCctvArtifacts : missionArtifacts.filter((artifact) => artifact.name === 'factory_overview.png'
    || artifact.name === 'factory_operator.png'
    || artifact.name === 'factory_low_operator.png'
    || /^factory_orbit_\d+\.png$/.test(artifact.name))
  const [sceneInput, setSceneInput] = useState<VirtualSceneInput | null>(null)
  const [sceneInputError, setSceneInputError] = useState('')
  const [frameIndex, setFrameIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const playingRef = useRef(false)
  const setReplayPlaying = (next: boolean) => {
    playingRef.current = next
    setPlaying(next)
  }
  const [sceneInputReady, setSceneInputReady] = useState(false)
  const [streamManifest, setStreamManifest] = useState<SynchronizedVideoManifest | null>(null)
  const [streamError, setStreamError] = useState('')
  const [speed, setSpeed] = useState(0.5)
  const [waypointFilter, setWaypointFilter] = useState('all')
  const [cameraMode, setCameraMode] = useState<ReplayCameraMode>('paired')
  const [evidenceFilter, setEvidenceFilter] = useState<ReplayEvidenceFilter>('all')
  const [assetUrls, setAssetUrls] = useState<Record<string, string>>({})
  const assetUrlsRef = useRef<Record<string, string>>({})
  const assetRequestsRef = useRef(new Map<string, AbortController>())

  useEffect(() => {
    let active = true
    setSceneInput(null)
    setSceneInputError('')
    const sourceArtifact = trajectoryArtifact || sceneInputArtifact
    setSceneInputReady(!sourceArtifact || !token)
    if (!sourceArtifact || !token) {
      setReplayPlaying(true)
      return () => { active = false }
    }
    void fetch(`${apiBase}/artifacts/${sourceArtifact.artifact_id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`${response.status}`)
      return response.json() as Promise<Record<string, unknown>>
    }).then((payload) => {
      if (!active) return
      if (trajectoryArtifact) {
        setSceneInput((current) => ({
          ...(current || {}),
          trajectory: Array.isArray(payload.trajectory) ? payload.trajectory as VirtualPose[] : [],
        }))
      } else {
        setSceneInput(payload as VirtualSceneInput)
      }
      setFrameIndex(0)
      setSceneInputReady(true)
      setReplayPlaying(true)
    }).catch((error) => {
      if (active) {
        setSceneInputError(error instanceof Error ? error.message : String(error))
        setSceneInputReady(true)
        setReplayPlaying(true)
      }
    })
    if (!trajectoryArtifact && sceneInputArtifact) {
      return () => { active = false }
    }
    let sceneActive = true
    if (sceneInputArtifact && trajectoryArtifact) {
      void fetch(`${apiBase}/artifacts/${sceneInputArtifact.artifact_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(async (response) => {
        if (!response.ok) throw new Error(`${response.status}`)
        return response.json() as Promise<VirtualSceneInput>
      }).then((payload) => {
        if (sceneActive) {
          setSceneInput((current) => ({ ...(current || {}), ...payload }))
          setSceneInputReady(true)
        }
      }).catch((error) => {
        if (sceneActive) {
          setSceneInputError(error instanceof Error ? error.message : String(error))
          setSceneInputReady(true)
        }
      })
    }
    return () => { active = false; sceneActive = false }
  }, [missionDetail.run_id, sceneInputArtifact?.artifact_id, token, trajectoryArtifact?.artifact_id])

  useEffect(() => {
    let active = true
    setStreamManifest(null)
    setStreamError('')
    if (!streamManifestArtifact || !token) return () => { active = false }
    void fetch(`${apiBase}/artifacts/${streamManifestArtifact.artifact_id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(async (response) => {
      if (!response.ok) throw new Error(`${response.status}`)
      return response.json() as Promise<SynchronizedVideoManifest>
    }).then((payload) => {
      if (!active) return
      if (!Array.isArray(payload.frames) || payload.frames.length < 2) {
        throw new Error('invalid synchronized video manifest')
      }
      setStreamManifest(payload)
    }).catch((error) => {
      if (active) setStreamError(error instanceof Error ? error.message : String(error))
    })
    return () => { active = false }
  }, [missionDetail.run_id, streamManifestArtifact?.artifact_id, token])

  useEffect(() => {
    setFrameIndex(0)
    setVideoTime(0)
    setReplayPlaying(false)
    setWaypointFilter('all')
    setCameraMode('paired')
    setEvidenceFilter('all')
  }, [missionDetail.run_id])

  const waypoints = useMemo<VirtualWaypoint[]>(() => {
    if (sceneInput?.waypoints?.length) return sceneInput.waypoints
    const configured = missionDetail.manifest?.site_config?.waypoints || site?.waypoints || []
    return configured.flatMap((item) => {
      const position = item.position
      if (!position || !Number.isFinite(position.x) || !Number.isFinite(position.y)) return []
      return [{
        waypoint_id: item.waypoint_id,
        device_id: item.device_id,
        device_name: item.device_name,
        zone: item.zone,
        asset_id: 'asset_id' in item && typeof item.asset_id === 'string' ? item.asset_id : undefined,
        x: position.x,
        y: position.y,
        z: position.z,
        yaw_deg: 'yaw_deg' in item && typeof item.yaw_deg === 'number' ? item.yaw_deg : 0,
      }]
    })
  }, [missionDetail.manifest?.site_config?.waypoints, sceneInput?.waypoints, site])

  const plannedRoute = useMemo(() => buildCollisionSafeRoute(waypoints, sceneInput?.trajectory?.length || 214), [sceneInput?.trajectory?.length, waypoints])
  const trajectory = useMemo<VirtualPose[]>(() => {
    if (localDemoMode && waypoints.length) return plannedRoute.trajectory
    if (sceneInput?.trajectory?.length) return sceneInput.trajectory
    if (!sceneInputReady && (trajectoryArtifact || sceneInputArtifact)) return []
    if (!waypoints.length) return [{ x: 0, y: 0, z: 0, yaw_deg: 0 }]
    return [{ x: 0, y: 0, z: 0, yaw_deg: 0 }, ...waypoints.map(({ x, y, z, yaw_deg }) => ({ x, y, z, yaw_deg }))]
  }, [plannedRoute.trajectory, sceneInput?.trajectory, sceneInputArtifact, sceneInputReady, trajectoryArtifact, waypoints])

  const waypointRouteTargets = localDemoMode && plannedRoute.inspectionTargets.length === waypoints.length
    ? plannedRoute.inspectionTargets
    : waypoints
  const waypointFrameIndices = useMemo(() => waypoints.map((waypoint, waypointIndex) => trajectory.reduce((closest, pose, index) => {
    const target = waypointRouteTargets[waypointIndex] || waypoint
    const currentDistance = Math.hypot(pose.x - target.x, pose.y - target.y)
    const closestDistance = Math.hypot(trajectory[closest].x - target.x, trajectory[closest].y - target.y)
    return currentDistance < closestDistance ? index : closest
  }, 0)), [trajectory, waypointRouteTargets, waypoints])
  useEffect(() => {
    if (!productMode || waypointFilter === 'all') return
    const waypointIndex = waypoints.findIndex((waypoint) => waypoint.waypoint_id === waypointFilter)
    if (waypointIndex >= 0) setFrameIndex(waypointFrameIndices[waypointIndex] || 0)
  }, [productMode, waypointFilter, waypointFrameIndices, waypoints])
  const maxFrameIndex = Math.max(0, trajectory.length - 1)
  const safeFrameIndex = Math.min(frameIndex, maxFrameIndex)
  const currentPose = trajectory[safeFrameIndex] || trajectory[0] || { x: 0, y: 0, z: 0, yaw_deg: 0 }
  const currentWaypointIndex = trajectory.length
    ? Math.max(0, waypointFrameIndices.reduce((current, waypointFrame, index) => safeFrameIndex >= waypointFrame ? index : current, 0))
    : 0
  const currentWaypoint = waypoints[currentWaypointIndex]
  const streamFrame = useMemo(() => {
    if (!streamManifest?.frames.length) return undefined
    return streamManifest.frames.reduce((closest, frame) => {
      return Math.abs(frame.trajectory_index - safeFrameIndex)
        < Math.abs(closest.trajectory_index - safeFrameIndex) ? frame : closest
    }, streamManifest.frames[0])
  }, [safeFrameIndex, streamManifest])
  const artifactsByName = useMemo(() => new Map(missionArtifacts.map((artifact) => [artifact.name, artifact])), [missionArtifacts])
  const robotVideoArtifact = streamManifest?.video_streams?.robot
    ? artifactsByName.get(streamManifest.video_streams.robot.artifact)
    : undefined
  const cctvVideoArtifact = streamManifest?.video_streams?.cctv
    ? artifactsByName.get(streamManifest.video_streams.cctv.artifact)
    : undefined
  const robotVideoRef = useRef<HTMLVideoElement | null>(null)
  const cctvVideoRef = useRef<HTMLVideoElement | null>(null)
  const [videoTime, setVideoTime] = useState(0)
  const lastUiClockUpdateRef = useRef(0)
  const lastRouteFrameRef = useRef(-1)
  const usingContinuousVideo = Boolean(
    robotVideoArtifact && cctvVideoArtifact
      && assetUrls[robotVideoArtifact.artifact_id]
      && assetUrls[cctvVideoArtifact.artifact_id],
  )
  const hasContinuousRobotStream = Boolean(streamManifest?.video_streams?.robot && robotVideoArtifact)
  const hasContinuousCctvStream = Boolean(streamManifest?.video_streams?.cctv && cctvVideoArtifact)
  const resultByWaypoint = useMemo(() => new Map(
    (missionDetail.result?.results || []).map((result) => [result.waypoint_id, result]),
  ), [missionDetail.result?.results])

  const mapGeometry = useMemo(() => {
    const minX = -4
    const maxX = 19
    const minY = -8.5
    const maxY = 7.5
    const plot = { left: 36, top: 22, right: 606, bottom: 266 }
    const spanX = maxX - minX
    const spanY = maxY - minY
    const project = (x: number, y: number) => [
      plot.left + ((x - minX) / spanX) * (plot.right - plot.left),
      plot.top + ((maxY - y) / spanY) * (plot.bottom - plot.top),
    ] as const
    const rect = (x: number, y: number, width: number, height: number) => {
      const [left, top] = project(x, y + height)
      const [right, bottom] = project(x + width, y)
      return { x: left, y: top, width: right - left, height: bottom - top }
    }
    const path = (points: Array<readonly [number, number]>) => points.map(([x, y], index) => {
      const [px, py] = project(x, y)
      return `${index === 0 ? 'M' : 'L'} ${px.toFixed(2)} ${py.toFixed(2)}`
    }).join(' ')
    const zones = [
      { id: 'UTIL-A', label: locale === 'zh' ? '蒸汽与分离器区' : 'Steam & separator', x: -3.5, y: 0.15, width: 9.8, height: 6.55, tone: 'process' },
      { id: 'ELEC-B', label: locale === 'zh' ? '低压配电区' : 'Low-voltage electrical', x: 5.9, y: -6.95, width: 3.55, height: 5.55, tone: 'electrical' },
      { id: 'UTIL-B', label: locale === 'zh' ? '换热与过滤区' : 'Heat exchange & filtration', x: 9.7, y: -6.95, width: 7.65, height: 12.05, tone: 'utility' },
      { id: 'MRO-C', label: locale === 'zh' ? '维护与备件区' : 'Maintenance & spares', x: -3.5, y: -7.75, width: 4.7, height: 4.0, tone: 'mro' },
      { id: 'SAFE-C', label: locale === 'zh' ? '消防与应急设施区' : 'Fire & emergency', x: 17.55, y: -6.95, width: 1.05, height: 12.05, tone: 'safety' },
    ].map((zone) => ({ ...zone, rect: rect(zone.x, zone.y, zone.width, zone.height) }))
    const equipment = [
      { kind: 'vessel' as const, id: 'V-101', label: locale === 'zh' ? '分离器' : 'Separator', center: project(-1.45, 2.9), radius: 17 },
      { kind: 'pipe' as const, id: 'PI-302', label: locale === 'zh' ? '蒸汽主管' : 'Steam header', rect: rect(2.45, 0.55, 3.15, 1.05) },
      { kind: 'cabinet' as const, id: 'MCC-04', label: locale === 'zh' ? '配电柜' : 'MCC', rect: rect(7.05, -3.05, 2.0, 0.95) },
      { kind: 'pump' as const, id: 'P-021', label: locale === 'zh' ? '循环泵组' : 'Pump skid', rect: rect(10.55, 2.65, 2.0, 1.55) },
      { kind: 'exchanger' as const, id: 'E-201', label: locale === 'zh' ? '换热器' : 'Exchanger', rect: rect(13.65, 2.25, 2.7, 1.5) },
      { kind: 'filter' as const, id: 'F-301', label: locale === 'zh' ? '过滤器' : 'Filter', center: project(15.05, -4.85), radius: 16 },
      { kind: 'fan' as const, id: 'HVAC-01', label: locale === 'zh' ? '排风机' : 'Exhaust fan', center: project(2.8, 5.55), radius: 13 },
      { kind: 'fire' as const, id: 'FIRE-01', label: locale === 'zh' ? '消防盘' : 'Fire reel', center: project(16.9, -3.85), radius: 11 },
      { kind: 'mro' as const, id: 'MRO-01', label: locale === 'zh' ? '维修工位' : 'MRO bay', rect: rect(-3.05, -7.35, 3.9, 1.85) },
    ]
    const equipmentLabelBoxes = equipment.map((item) => {
      let x: number
      let y: number
      let anchor: 'start' | 'middle' | 'end'
      if ('center' in item && item.center) {
        const [centerX, centerY] = item.center
        const radius = item.radius || 12
        if (item.kind === 'fan') {
          x = centerX - radius - 4
          y = centerY + 3
          anchor = 'end'
        } else if (item.kind === 'fire') {
          x = centerX + radius + 4
          y = centerY + radius + 14
          anchor = 'start'
        } else {
          x = centerX + radius + 4
          y = centerY + 3
          anchor = 'start'
        }
      } else if ('rect' in item) {
        x = item.rect.x + item.rect.width / 2
        y = item.rect.y + item.rect.height + 11
        anchor = 'middle'
      } else {
        return null
      }
      const width = item.id.length * 6.63
      const left = anchor === 'start' ? x : anchor === 'end' ? x - width : x - width / 2
      return { left, top: y - 13.125, right: left + width, bottom: y }
    }).filter((box): box is { left: number; top: number; right: number; bottom: number } => box !== null)
    const serviceLanePoints: Array<Array<readonly [number, number]>> = [
      [[-3.35, -0.9], [1.25, -0.9], [5.15, -0.9], [8.85, -0.9], [12.7, -0.9], [17.35, -0.9]],
      [[6.2, -6.65], [6.2, -4.15], [6.2, -1.1], [6.2, 2.05], [6.2, 6.3]],
      [[9.8, 5.55], [13.25, 5.55], [17.25, 5.55]],
    ]
    const serviceLanes = serviceLanePoints.map((points) => path(points))
    const processPipePoints: Array<Array<readonly [number, number]>> = [
      [[-3.2, 1.25], [-1.45, 1.25], [1.3, 1.25], [4.05, 1.25], [6.1, 1.25], [8.2, 0.55]],
      [[8.25, 4.75], [11.3, 4.75], [14.45, 4.75], [16.9, 3.95], [16.9, -3.85]],
      [[11.55, 2.1], [11.55, 0.15], [15.05, 0.15], [15.05, -4.85]],
    ]
    const processPiping = processPipePoints.map((points) => path(points))
    const ticksX = [-4, 0, 4, 8, 12, 16, 19].map((value) => ({ value, x: project(value, minY)[0] }))
    const ticksY = [-8, -4, 0, 4, 7].map((value) => ({ value, y: project(minX, value)[1] }))
    const routeDirectionMarkers = trajectory.filter((_, index) => index > 10 && index % 22 === 0).map((point) => {
      const [x, y] = project(point.x, point.y)
      return { x, y, angle: -(point.yaw_deg || 0) }
    })
    const waypointPoints = waypoints.map((point) => project(point.x, point.y))
    return {
      project,
      trajectoryPoints: trajectory.map((point) => project(point.x, point.y)),
      waypointPoints,
      waypointLabels: placeWaypointMapLabels(waypointPoints, equipmentLabelBoxes),
      inspectionLinks: waypoints.map((waypoint, index) => ({
        asset: project(waypoint.x, waypoint.y),
        target: project(waypointRouteTargets[index]?.x ?? waypoint.x, waypointRouteTargets[index]?.y ?? waypoint.y),
      })),
      routeDirectionMarkers,
      plot,
      boundary: rect(-3.7, -8.05, 22.15, 14.95),
      zones,
      equipment,
      serviceLanes,
      processPiping,
      ticksX,
      ticksY,
    }
  }, [locale, trajectory, waypointRouteTargets, waypoints])

  const streamRobotArtifact = streamFrame ? artifactsByName.get(streamFrame.robot_artifact) : undefined
  const streamCctvArtifact = streamFrame ? artifactsByName.get(streamFrame.cctv_artifact) : undefined
  const nextStreamFrame = streamManifest?.frames.find((frame) => frame.sequence_index === (streamFrame?.sequence_index ?? -1) + 1)
  const nextReplayFrameIndex = streamManifest?.frames.find((frame) => frame.trajectory_index > safeFrameIndex)?.trajectory_index
    ?? Math.min(maxFrameIndex, safeFrameIndex + 1)
  const nextStreamRobotArtifact = nextStreamFrame ? artifactsByName.get(nextStreamFrame.robot_artifact) : undefined
  const nextStreamCctvArtifact = nextStreamFrame ? artifactsByName.get(nextStreamFrame.cctv_artifact) : undefined
  const currentRobotArtifact = streamRobotArtifact || (currentWaypoint
    ? robotArtifacts.find((artifact) => artifact.name === `virtual_world__${currentWaypoint.waypoint_id}__rgb_camera.png`)
    : robotArtifacts[0])
  const cctvName = currentWaypoint ? `factory_cctv__${currentWaypoint.waypoint_id}.png` : ''
  const orbitName = `factory_orbit_${String((currentWaypointIndex % 10) + 1).padStart(2, '0')}.png`
  const currentFixedArtifact = streamCctvArtifact || fixedCameraArtifacts.find((artifact) => artifact.name === cctvName)
    || fixedCameraArtifacts.find((artifact) => artifact.name === orbitName)
    || fixedCameraArtifacts.find((artifact) => artifact.name === 'factory_overview.png')
    || fixedCameraArtifacts[0]
  const evidenceIsVerified = Boolean(streamFrame?.same_route_frame && streamRobotArtifact && streamCctvArtifact)
  const evidenceStatus: ReplayEvidenceFilter = evidenceIsVerified ? 'verified' : 'attention'
  const evidenceMatches = evidenceFilter === 'all' || evidenceFilter === evidenceStatus
  const robotVisible = cameraMode !== 'cctv'
  const cctvVisible = cameraMode !== 'robot'
  const selectedFilterWaypoint = waypointFilter === 'all'
    ? undefined
    : waypoints.find((waypoint) => waypoint.waypoint_id === waypointFilter)

  const setReplayFrame = useCallback((targetFrame: number, pause = true) => {
    const boundedFrame = Math.max(0, Math.min(maxFrameIndex, Math.round(targetFrame)))
    setFrameIndex(boundedFrame)
    if (usingContinuousVideo && streamManifest?.frames.length) {
      const selected = streamManifest.frames.reduce((closest, frame) => (
        Math.abs(frame.trajectory_index - boundedFrame)
          < Math.abs(closest.trajectory_index - boundedFrame) ? frame : closest
      ), streamManifest.frames[0])
      const seconds = selected.sequence_index * streamManifest.frame_duration_s
      setVideoTime(seconds)
      lastUiClockUpdateRef.current = performance.now()
      lastRouteFrameRef.current = boundedFrame - 1
      if (robotVideoRef.current) robotVideoRef.current.currentTime = seconds
      if (cctvVideoRef.current) cctvVideoRef.current.currentTime = seconds
    }
    if (pause) setReplayPlaying(false)
  }, [maxFrameIndex, streamManifest, usingContinuousVideo])

  const handleContinuousVideoFrame = useCallback((seconds: number) => {
    if (!streamManifest?.frames.length) return
    const now = performance.now()
    // Keep the decoder at its native cadence while publishing the operational
    // clock and route geometry at a readable UI cadence.
    if (now - lastUiClockUpdateRef.current >= 80) {
      lastUiClockUpdateRef.current = now
      setVideoTime(seconds)
    }
    // The robot stream is the master clock. Per-frame CCTV seeks flush the
    // browser decoder and create visible judder, so correct only real drift.
    const cctvVideo = cctvVideoRef.current
    if (playingRef.current && cctvVideo && !cctvVideo.seeking
      && Math.abs(cctvVideo.currentTime - seconds) > 0.18) {
      cctvVideo.currentTime = seconds
    }
    const frameDuration = Math.max(0.001, streamManifest.frame_duration_s)
    const streamPosition = Math.max(0, Math.min(
      streamManifest.frames.length - 1,
      seconds / frameDuration,
    ))
    const lowerIndex = Math.floor(streamPosition)
    const upperIndex = Math.min(streamManifest.frames.length - 1, lowerIndex + 1)
    const alpha = streamPosition - lowerIndex
    const lower = streamManifest.frames[lowerIndex]
    const upper = streamManifest.frames[upperIndex]
    const routeFrame = Math.round(lower.trajectory_index + (upper.trajectory_index - lower.trajectory_index) * alpha)
    if (lastRouteFrameRef.current !== routeFrame) {
      lastRouteFrameRef.current = routeFrame
      setFrameIndex(routeFrame)
    }
  }, [streamManifest])

  useEffect(() => {
    if (!usingContinuousVideo) return
    const videos = [robotVideoRef.current, cctvVideoRef.current].filter(
      (video): video is HTMLVideoElement => Boolean(video),
    )
    videos.forEach((video) => { video.playbackRate = speed })
    if (playing) {
      const robotVideo = robotVideoRef.current
      const cctvVideo = cctvVideoRef.current
      if (robotVideo && cctvVideo && cctvVideo.readyState >= HTMLMediaElement.HAVE_METADATA
        && Math.abs(cctvVideo.currentTime - robotVideo.currentTime) > 0.06) {
        cctvVideo.currentTime = robotVideo.currentTime
      }
      videos.forEach((video) => { void video.play().catch(() => undefined) })
    } else {
      videos.forEach((video) => video.pause())
    }
  }, [playing, robotVideoArtifact?.artifact_id, cctvVideoArtifact?.artifact_id, speed, usingContinuousVideo])

  useEffect(() => {
    const handleCommand = (event: Event) => {
      const detail = (event as CustomEvent<InspectionSyncCommand>).detail
      if (!detail) return
      if (detail.type === 'toggle') {
        setReplayPlaying(!playingRef.current)
      } else if (detail.type === 'play') {
        setReplayPlaying(true)
      } else if (detail.type === 'pause') {
        setReplayPlaying(false)
      } else if (detail.type === 'reset') {
        setReplayFrame(0)
      } else if (detail.type === 'next') {
        setReplayFrame(nextReplayFrameIndex)
      } else if (detail.type === 'seek' && typeof detail.frameIndex === 'number') {
        setReplayFrame(detail.frameIndex)
      }
    }
    window.addEventListener('inspection-sync-command', handleCommand)
    return () => window.removeEventListener('inspection-sync-command', handleCommand)
  }, [nextReplayFrameIndex, setReplayFrame])

  useEffect(() => {
    if (!playing || maxFrameIndex <= 0 || usingContinuousVideo) return
    const playbackIntervalMs = streamManifest
      ? Math.max(180, (streamManifest.frame_duration_s * 1000) / speed)
      : Math.max(240, 240 / speed)
    const timer = window.setInterval(() => {
      if (!playingRef.current) return
      setFrameIndex((current) => {
        if (current >= maxFrameIndex) {
          setReplayPlaying(false)
          return maxFrameIndex
        }
        return current + 1
      })
    }, playbackIntervalMs)
    return () => window.clearInterval(timer)
  }, [maxFrameIndex, playing, speed, streamManifest, usingContinuousVideo])

  useEffect(() => {
    const pairedContinuousStreamsAvailable = hasContinuousRobotStream && hasContinuousCctvStream
    const needed = [
      currentRobotArtifact,
      currentFixedArtifact,
      ...(pairedContinuousStreamsAvailable ? [] : [nextStreamRobotArtifact, nextStreamCctvArtifact]),
      robotVideoArtifact,
      cctvVideoArtifact,
    ]
      .filter((artifact): artifact is Artifact => Boolean(artifact))
    needed.forEach((artifact) => {
      // A route-frame change must not discard a video download that is still
      // buffering. Share pending requests until completion or component cleanup.
      if (assetUrlsRef.current[artifact.artifact_id] || assetRequestsRef.current.has(artifact.artifact_id)) return
      const controller = new AbortController()
      assetRequestsRef.current.set(artifact.artifact_id, controller)
      void fetch(`${apiBase}/artifacts/${artifact.artifact_id}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      }).then(async (response) => {
        if (!response.ok) throw new Error(`${response.status}`)
        return URL.createObjectURL(await response.blob())
      }).then((url) => {
        if (controller.signal.aborted) {
          URL.revokeObjectURL(url)
          return
        }
        assetUrlsRef.current[artifact.artifact_id] = url
        setAssetUrls((current) => ({ ...current, [artifact.artifact_id]: url }))
      }).catch(() => undefined).finally(() => {
        if (assetRequestsRef.current.get(artifact.artifact_id) === controller) {
          assetRequestsRef.current.delete(artifact.artifact_id)
        }
      })
    })
  }, [currentFixedArtifact?.artifact_id, currentRobotArtifact?.artifact_id,
    cctvVideoArtifact?.artifact_id, hasContinuousCctvStream,
    hasContinuousRobotStream, nextStreamCctvArtifact?.artifact_id,
    nextStreamRobotArtifact?.artifact_id, robotVideoArtifact?.artifact_id, token])

  useEffect(() => () => {
    assetRequestsRef.current.forEach((controller) => controller.abort())
    assetRequestsRef.current.clear()
    Object.values(assetUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
    assetUrlsRef.current = {}
  }, [])

  const currentResult = currentWaypoint ? resultByWaypoint.get(currentWaypoint.waypoint_id) : undefined
  const progress = maxFrameIndex ? safeFrameIndex / maxFrameIndex : 0
  const routeFrameDuration = streamManifest?.frame_duration_s || 0.24
  const elapsedSeconds = usingContinuousVideo
    ? videoTime / speed
    : (streamFrame?.sequence_index ?? safeFrameIndex) * routeFrameDuration / speed
  const continuousDuration = streamManifest?.video_streams?.robot?.duration_s
    || streamManifest?.video_streams?.cctv?.duration_s
  const totalSeconds = usingContinuousVideo && continuousDuration
    ? continuousDuration / speed
    : ((streamManifest?.frame_count || maxFrameIndex + 1) - 1) * routeFrameDuration / speed
  const sharedFrameLabel = streamFrame
    ? `F${String(streamFrame.sequence_index + 1).padStart(3, '0')} / F${String(streamManifest?.frame_count || 0).padStart(3, '0')}`
    : `F${String(safeFrameIndex + 1).padStart(3, '0')} / F${String(maxFrameIndex + 1).padStart(3, '0')}`
  const sharedClockLabel = replayClock(elapsedSeconds)
  const sharedTimecode = replayTimecode(elapsedSeconds, streamManifest?.presentation_fps || 30)
  const routePoints = mapGeometry.trajectoryPoints.map(([x, y]) => `${x},${y}`).join(' ')
  const completedPoints = mapGeometry.trajectoryPoints.slice(0, safeFrameIndex + 1).map(([x, y]) => `${x},${y}`).join(' ')
  const [robotX, robotY] = mapGeometry.project(currentPose.x, currentPose.y)
  const robotLabelX = Math.min(robotX + 16, 530)
  const robotLabelY = Math.max(robotY - 29, 29)
  const yaw = -(currentPose.yaw_deg || 0)
  const frameRouteIndex = streamFrame?.trajectory_index ?? safeFrameIndex
  const frameRenderIndex = streamFrame?.render_frame ?? safeFrameIndex + 1
  const frameResolution = (streamManifest?.presentation_resolution || streamManifest?.resolution)
    ? `${(streamManifest.presentation_resolution || streamManifest.resolution)!.width} × ${(streamManifest.presentation_resolution || streamManifest.resolution)!.height}`
    : '—'
  const frameSource = sourceLabel(streamRobotArtifact?.source || currentFixedArtifact?.source, locale)
  const routeDistanceLabel = `${plannedRoute.routeDistance.toFixed(1)} m`
  const openArtifact = (artifact: Artifact | undefined) => {
    if (!artifact) return
    const url = assetUrls[artifact.artifact_id]
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }
  useEffect(() => {
    window.dispatchEvent(new CustomEvent<SceneSyncState>('inspection-sync-frame', {
      detail: {
        timecode: sharedTimecode,
        frameIndex: safeFrameIndex,
        routeFrame: frameRouteIndex,
        renderFrame: frameRenderIndex,
        streamFrameIndex: streamFrame?.sequence_index ?? null,
        streamFrameCount: streamManifest?.frame_count ?? null,
        playing,
        waypointId: currentWaypoint?.waypoint_id || null,
        deviceName: currentWaypoint?.device_name || null,
        pose: currentPose,
      },
    }))
  }, [currentPose, currentWaypoint?.device_name, currentWaypoint?.waypoint_id, frameRenderIndex, frameRouteIndex, playing, safeFrameIndex, sharedTimecode, streamFrame?.sequence_index, streamManifest?.frame_count])

  return <section className="synchronized-replay" aria-label={copy.synchronizedReplay}>
    <div className="detail-section-heading replay-heading">
      <div><h3>{copy.synchronizedReplay}</h3><p>{copy.synchronizedReplayDescription}</p></div>
      <div className="replay-heading-badges"><span className="replay-route-safety-badge"><ShieldCheck size={12} />{copy.collisionSafeRoute}</span><span className="replay-source-badge"><span />{streamManifest ? `${streamManifest.video_streams ? copy.continuousVideoStream : copy.syncedImageStream} · ${streamManifest.frame_count} ${copy.routeFrames}` : copy.syntheticReplay}</span>{productMode && <span className="replay-version-chip"><BadgeCheck size={12} />{copy.v33Workbench}</span>}</div>
    </div>
    <div className="replay-status-strip">
      <span><Route size={14} />{copy.trajectory} <strong>{Math.round(progress * 100)}%</strong></span>
      <span><MapPin size={14} />{currentWaypoint ? currentWaypoint.waypoint_id : '—'} <strong>{deviceLabel(currentWaypoint?.device_name, locale) || copy.startPosition}</strong></span>
      <span><Video size={14} />{copy.robotVideoStream} <strong>{currentRobotArtifact ? currentRobotArtifact.name.replace('robot_rgb_stream__', 'RGB · ').replace('.png', '') : '—'}</strong></span>
      <span><Clock3 size={14} />{copy.syncFrame} <strong>{sharedFrameLabel} · {sharedClockLabel}</strong></span>
    </div>
    {productMode && <>
      <div className="replay-workbench-bar">
        <span className="replay-workbench-label"><SlidersHorizontal size={14} />{copy.evidenceWorkbench}</span>
        <label><span>{copy.filterWaypoint}</span><select aria-label={copy.filterWaypoint} value={waypointFilter} onChange={(event) => setWaypointFilter(event.target.value)}><option value="all">{copy.allWaypoints}</option>{waypoints.map((waypoint) => <option value={waypoint.waypoint_id} key={waypoint.waypoint_id}>{waypoint.waypoint_id} · {deviceLabel(waypoint.device_name, locale)}</option>)}</select></label>
        <label><span>{copy.filterCamera}</span><select aria-label={copy.filterCamera} value={cameraMode} onChange={(event) => setCameraMode(event.target.value as ReplayCameraMode)}><option value="paired">{copy.allCameraViews}</option><option value="robot">{copy.robotOnly}</option><option value="cctv">{copy.cctvOnly}</option></select></label>
        <label><span>{copy.filterEvidence}</span><select aria-label={copy.filterEvidence} value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as ReplayEvidenceFilter)}><option value="all">{copy.allEvidence}</option><option value="verified">{copy.verifiedEvidence}</option><option value="attention">{copy.attentionEvidence}</option></select></label>
      </div>
      <p className="replay-workbench-description">{copy.evidenceWorkbenchDescription}</p>
      {selectedFilterWaypoint && <div className="replay-filter-context"><MapPin size={13} /><span>{selectedFilterWaypoint.waypoint_id} · {deviceLabel(selectedFilterWaypoint.device_name, locale)}</span><small>{zoneLabel(selectedFilterWaypoint.zone, locale)}</small></div>}
    </>}
    <div className="replay-layout">
      <div className="replay-map-panel">
        <div className="replay-panel-heading"><span><Factory size={14} />{copy.plantTopDown}</span><small>{copy.coordinateReference} · {trajectory.length} {copy.routeFrames}</small></div>
        <div className="replay-map-canvas">
          <div className="replay-map-readout" aria-live="polite">
            <span><small>{copy.sceneRouteIndex}</small><strong>R{String(frameRouteIndex).padStart(3, '0')} / F{String(frameRenderIndex).padStart(4, '0')}</strong></span>
            <span><small>{copy.waypoint}</small><strong>{currentWaypoint?.waypoint_id || '—'}</strong></span>
            <span><small>{copy.robotPosition}</small><strong>{currentPose.x.toFixed(2)}, {currentPose.y.toFixed(2)} m</strong></span>
          </div>
          <svg className="replay-map-svg replay-floor-plan" viewBox="0 0 640 300" role="img" aria-label={`${copy.plantTopDown} · ${copy.coordinateReference}`} data-route-planner="collision-safe-aisles" data-route-frame-count={trajectory.length} data-route-current-frame={safeFrameIndex}>
            <title>{`${copy.plantTopDown} · ${copy.coordinateReference}`}</title>
            <defs>
              <pattern id="replay-floor-grid-v36" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" className="replay-floor-grid-line" />
              </pattern>
            </defs>
            <rect className="replay-map-surface" x="0" y="0" width="640" height="300" />
            <rect className="replay-floor-grid" x={mapGeometry.plot.left} y={mapGeometry.plot.top} width={mapGeometry.plot.right - mapGeometry.plot.left} height={mapGeometry.plot.bottom - mapGeometry.plot.top} />
            <rect className="replay-floor-boundary" x={mapGeometry.boundary.x} y={mapGeometry.boundary.y} width={mapGeometry.boundary.width} height={mapGeometry.boundary.height} />
            <path className="replay-map-axis" d={`M ${mapGeometry.plot.left} ${mapGeometry.plot.bottom} H ${mapGeometry.plot.right} M ${mapGeometry.plot.left} ${mapGeometry.plot.top} V ${mapGeometry.plot.bottom}`} />
            <g className="replay-map-compass" aria-hidden="true" transform="translate(574 42)">
              <circle cx="0" cy="0" r="13" />
              <path d="M 0 -8 L 4 5 L 0 2 L -4 5 Z" />
              <text x="0" y="-16">N</text>
            </g>
            <g className="replay-map-scale" aria-hidden="true" transform="translate(42 278)">
              <path d="M 0 0 H 48 M 0 -4 V 4 M 48 -4 V 4" />
              <text x="0" y="15">0</text>
              <text x="48" y="15">2 m</text>
            </g>
            <g className="replay-floor-zones">
              {mapGeometry.zones.map((zone) => {
                const zoneLabelOnRight = zone.id === 'UTIL-B'
                return <g className={`replay-floor-zone replay-floor-zone-${zone.tone}`} key={zone.id}>
                <title>{`${zone.id} · ${zone.label}`}</title>
                <rect x={zone.rect.x} y={zone.rect.y} width={zone.rect.width} height={zone.rect.height} />
                <text textAnchor={zoneLabelOnRight ? 'end' : 'start'} x={zoneLabelOnRight ? zone.rect.x + zone.rect.width - 7 : zone.rect.x + 7} y={zone.rect.y + 13}>{zone.id}</text>
              </g>})}
            </g>
            <g className="replay-floor-lanes" aria-label={copy.serviceLane}>
              {mapGeometry.serviceLanes.map((lane, index) => <path className="replay-floor-lane" d={lane} key={`lane-${index}`} />)}
            </g>
            <g className="replay-floor-piping" aria-label={copy.processPiping}>
              {mapGeometry.processPiping.map((pipe, index) => <path className="replay-floor-pipe" d={pipe} key={`pipe-${index}`} />)}
            </g>
            <polyline className="replay-route-clearance" points={routePoints} />
            <g className="replay-floor-equipment" aria-label={copy.equipmentZone}>
              {mapGeometry.equipment.map((item) => {
                if ('center' in item && item.center) {
                  const [x, y] = item.center
                  const radius = item.radius || 12
                  const labelPlacement = item.kind === 'fan'
                    ? { x: x - radius - 4, y: y + 3, className: 'replay-equipment-label replay-equipment-label-left' }
                    : item.kind === 'fire'
                      ? { x: x + radius + 4, y: y + radius + 14, className: 'replay-equipment-label' }
                      : { x: x + radius + 4, y: y + 3, className: 'replay-equipment-label' }
                  return <g className={`replay-floor-equipment-item replay-floor-equipment-${item.kind}`} key={item.id}>
                    <title>{`${item.id} · ${item.label}`}</title>
                    <circle className="replay-equipment-footprint" cx={x} cy={y} r={radius} />
                    <circle className="replay-equipment-core" cx={x} cy={y} r={Math.max(4, radius - 8)} />
                    {item.kind === 'fan' && <path className="replay-equipment-fan" d={`M ${x} ${y - 8} L ${x + 8} ${y + 6} L ${x - 8} ${y + 6} Z`} />}
                    {item.kind === 'fire' && <circle className="replay-equipment-fire" cx={x} cy={y} r="4" />}
                    {item.kind === 'vessel' && <path className="replay-equipment-cross" d={`M ${x - 8} ${y} H ${x + 8} M ${x} ${y - 8} V ${y + 8}`} />}
                    <text className={labelPlacement.className} x={labelPlacement.x} y={labelPlacement.y}>{item.id}</text>
                  </g>
                }
                const { x, y, width, height } = item.rect
                return <g className={`replay-floor-equipment-item replay-floor-equipment-${item.kind}`} key={item.id}>
                  <rect className="replay-equipment-rect" x={x} y={y} width={width} height={height} />
                  {item.kind === 'pipe' && <><circle className="replay-equipment-valve" cx={x + width * .25} cy={y + height / 2} r="4" /><circle className="replay-equipment-valve" cx={x + width * .72} cy={y + height / 2} r="4" /><path className="replay-equipment-detail-line" d={`M ${x + width * .4} ${y + 4} V ${y + height - 4} M ${x + width * .58} ${y + 4} V ${y + height - 4}`} /></>}
                  {item.kind === 'cabinet' && <><path className="replay-equipment-detail-line" d={`M ${x + width * .25} ${y + 4} V ${y + height - 4} M ${x + width * .5} ${y + 4} V ${y + height - 4} M ${x + width * .75} ${y + 4} V ${y + height - 4}`} /><circle className="replay-equipment-warning" cx={x + width - 7} cy={y + height / 2} r="3" /></>}
                  {item.kind === 'pump' && <><circle className="replay-equipment-core" cx={x + width * .3} cy={y + height / 2} r="7" /><circle className="replay-equipment-core" cx={x + width * .7} cy={y + height / 2} r="7" /><path className="replay-equipment-detail-line" d={`M ${x + width * .3 + 7} ${y + height / 2} H ${x + width * .7 - 7}`} /></>}
                  {item.kind === 'exchanger' && <><path className="replay-equipment-detail-line" d={`M ${x + width * .3} ${y + 3} V ${y + height - 3} M ${x + width * .5} ${y + 3} V ${y + height - 3} M ${x + width * .7} ${y + 3} V ${y + height - 3}`} /><circle className="replay-equipment-flange" cx={x + 4} cy={y + height / 2} r="4" /><circle className="replay-equipment-flange" cx={x + width - 4} cy={y + height / 2} r="4" /></>}
                  {item.kind === 'mro' && <><path className="replay-equipment-detail-line" d={`M ${x + 6} ${y + height * .38} H ${x + width - 6} M ${x + 6} ${y + height * .7} H ${x + width - 6}`} /><path className="replay-equipment-rack" d={`M ${x + 9} ${y + 4} V ${y + height - 4} M ${x + width - 9} ${y + 4} V ${y + height - 4}`} /></>}
                  <title>{`${item.id} · ${item.label}`}</title>
                  <text className="replay-equipment-label" x={x + width / 2} y={y + height + 11}>{item.id}</text>
                </g>
              })}
            </g>
            <g className="replay-inspection-links" aria-label={copy.inspectionWaypoint}>
              {mapGeometry.inspectionLinks.map(({ asset, target }, index) => <line key={`inspection-link-${index}`} x1={asset[0]} y1={asset[1]} x2={target[0]} y2={target[1]} />)}
            </g>
            <polyline className="replay-route-base" points={routePoints} />
            <polyline className="replay-route-progress" points={completedPoints} />
            <g className="replay-route-direction-markers" aria-hidden="true">
              {mapGeometry.routeDirectionMarkers.map((marker, index) => <path key={`route-direction-${index}`} d="M 7 0 L -5 -4 L -2 0 L -5 4 Z" transform={`translate(${marker.x} ${marker.y}) rotate(${marker.angle})`} />)}
            </g>
            <g className="replay-route-start">
              <circle cx={mapGeometry.trajectoryPoints[0]?.[0] || mapGeometry.plot.left} cy={mapGeometry.trajectoryPoints[0]?.[1] || mapGeometry.plot.bottom} r="4" />
              <text x={(mapGeometry.trajectoryPoints[0]?.[0] || mapGeometry.plot.left) + 7} y={(mapGeometry.trajectoryPoints[0]?.[1] || mapGeometry.plot.bottom) - 6}>START</text>
            </g>
            {mapGeometry.waypointPoints.map(([x, y], index) => {
              const waypoint = waypoints[index]
              const label = mapGeometry.waypointLabels[index]
              const result = waypoint ? resultByWaypoint.get(waypoint.waypoint_id) : undefined
              const status = result?.assessment?.severity?.toLowerCase() || 'unknown'
              const state = index < currentWaypointIndex ? 'visited' : index === currentWaypointIndex ? 'current' : 'planned'
              const labelLeft = label.anchor === 'start' ? label.x : label.anchor === 'end' ? label.x - 38 : label.x - 19
              return <g className={`replay-waypoint replay-waypoint-${state}`} key={waypoint.waypoint_id}>
                <title>{`${waypoint.waypoint_id} · ${deviceLabel(waypoint.device_name, locale)} · X ${waypoint.x.toFixed(2)} / Y ${waypoint.y.toFixed(2)} m`}</title>
                <circle cx={x} cy={y} r="14" />
                <circle className={`replay-waypoint-dot replay-waypoint-${status}`} cx={x} cy={y} r="6" />
                <line className="replay-waypoint-leader" data-waypoint-label-line="true" x1={label.leader.x1} y1={label.leader.y1} x2={label.leader.x2} y2={label.leader.y2} />
                <rect className="replay-waypoint-label-bg" data-waypoint-label-bg="true" x={labelLeft} y={label.y - 11} width="38" height="13" rx="2" />
                <text className="replay-waypoint-id" data-waypoint-label="true" textAnchor={label.anchor} x={label.x} y={label.y}>WP {String(index + 1).padStart(2, '0')}</text>
              </g>
            })}
            <g className="replay-robot-marker" transform={`translate(${robotX} ${robotY}) rotate(${yaw})`}>
              <circle r="13" />
              <path d="M 8 0 L -4 -6 L -4 6 Z" />
            </g>
            <g className="replay-robot-label" transform={`translate(${robotLabelX} ${robotLabelY})`}>
              <title>{`RBT · X ${currentPose.x.toFixed(2)} / Y ${currentPose.y.toFixed(2)} m`}</title>
              <rect x="0" y="-10" width="38" height="20" rx="2" />
              <text x="6" y="-1">RBT</text>
            </g>
            <g className="replay-map-ticks">
              {mapGeometry.ticksX.map((tick) => <g key={`x-${tick.value}`}><path d={`M ${tick.x} ${mapGeometry.plot.bottom} v 4`} /><text x={tick.x} y={mapGeometry.plot.bottom + 14}>{tick.value}</text></g>)}
              {mapGeometry.ticksY.map((tick) => <g key={`y-${tick.value}`}><path d={`M ${mapGeometry.plot.left - 4} ${tick.y} h 4`} /><text x={mapGeometry.plot.left - 9} y={tick.y + 3}>{tick.value}</text></g>)}
            </g>
            <text className="replay-map-label replay-map-label-x" x="606" y="293">X / m</text>
            <text className="replay-map-label replay-map-label-y" x="10" y="26">Y / m</text>
          </svg>
          <div className="replay-map-live-strip" aria-live="polite">
            <div className="replay-map-live-primary">
              <span className="replay-map-live-kicker"><Activity size={13} />{copy.currentInspection}</span>
              <strong>{currentWaypoint?.waypoint_id || '—'}</strong>
              <span className="replay-map-live-device">{deviceLabel(currentWaypoint?.device_name, locale) || copy.startPosition}</span>
            </div>
            <div className="replay-map-live-value"><span>{copy.xCoordinate}</span><strong>{currentPose.x.toFixed(2)} m</strong></div>
            <div className="replay-map-live-value"><span>{copy.yCoordinate}</span><strong>{currentPose.y.toFixed(2)} m</strong></div>
            <div className="replay-map-live-value"><span>{copy.status}</span><strong>{playing ? copy.playing : safeFrameIndex >= maxFrameIndex ? copy.paused : copy.ready}</strong></div>
          </div>
          <div className="replay-map-legend"><span><i className="replay-legend-line" />{copy.completedRoute}</span><span><i className="replay-legend-plan" />{copy.plannedRoute}</span><span><i className="replay-legend-dot" />{copy.robotPosition}</span><span><i className="replay-legend-node" />{copy.inspectionWaypoint}</span><span><i className="replay-legend-zone" />{copy.equipmentZone}</span><span><i className="replay-legend-lane" />{copy.serviceLane}</span></div>
        </div>
        <div className="replay-route-metrics" aria-label={copy.routePlanner}>
          <div><span><Route size={13} />{copy.routePlanner}</span><strong>{copy.collisionSafeRoute}</strong></div>
          <div><span><ShieldCheck size={13} />{copy.safetyClearance}</span><strong>0.45 m</strong></div>
          <div><span><Layers3 size={13} />{copy.routeSegments}</span><strong>{plannedRoute.segmentCount}</strong></div>
          <div><span><MapPin size={13} />{copy.routeDistance}</span><strong>{routeDistanceLabel}</strong></div>
        </div>
        <dl className="replay-pose-grid">
          <div><dt>{copy.xCoordinate}</dt><dd>{currentPose.x.toFixed(2)} m</dd></div>
          <div><dt>{copy.yCoordinate}</dt><dd>{currentPose.y.toFixed(2)} m</dd></div>
          <div><dt>{copy.heading}</dt><dd>{(currentPose.yaw_deg || 0).toFixed(0)}°</dd></div>
          <div><dt>{copy.status}</dt><dd>{playing ? copy.playing : safeFrameIndex >= maxFrameIndex ? copy.paused : copy.ready}</dd></div>
        </dl>
      </div>
      <div className={`replay-feed-grid replay-feed-grid-${cameraMode}`}>
        {evidenceMatches ? <>
          {robotVisible && <article className="replay-feed-card">
            <header><span><Video size={14} />{copy.robotHeadRgbStream}</span><small>{currentRobotArtifact ? (streamManifest ? `F${String((streamFrame?.sequence_index || 0) + 1).padStart(3, '0')}` : virtualCameraLabel(currentRobotArtifact.name, locale)) : '—'}</small></header>
            <div className="replay-feed-image">{hasContinuousRobotStream ? <ContinuousVideoFeed
              src={assetUrls[robotVideoArtifact!.artifact_id]}
              posterUrl={currentRobotArtifact ? assetUrls[currentRobotArtifact.artifact_id] : undefined}
              videoRef={robotVideoRef}
              alt={copy.robotHeadRgbStream}
              cameraKind="robot"
              locale={locale}
              playing={playing}
              playbackRate={speed}
              fpsHint={streamManifest?.video_streams?.robot?.fps || streamManifest?.presentation_fps}
              frameLabel={sharedFrameLabel}
              sourceLabel={locale === 'zh' ? '机器人头顶 / RGB · MP4' : 'ROBOT HEAD / RGB · MP4'}
              onFrame={handleContinuousVideoFrame}
              onEnded={() => setReplayPlaying(false)}
            /> : currentRobotArtifact && assetUrls[currentRobotArtifact.artifact_id] ? <RealtimeCameraFeed
              primaryUrl={assetUrls[currentRobotArtifact.artifact_id]}
              nextUrl={nextStreamRobotArtifact ? assetUrls[nextStreamRobotArtifact.artifact_id] : assetUrls[currentRobotArtifact.artifact_id]}
              alt={copy.robotHeadRgbStream}
              cameraKind="robot"
              locale={locale}
              playing={playing}
              transitionMs={Math.max(180, (routeFrameDuration * 1000) / speed)}
              frameLabel={sharedFrameLabel}
              sourceLabel={locale === 'zh' ? '机器人头顶 / RGB' : 'ROBOT HEAD / RGB'}
            /> : <span><Video size={18} />{copy.robotHeadLoading}</span>}
              {currentRobotArtifact && <button type="button" className="replay-open-evidence" title={copy.openEvidence} aria-label={copy.openEvidence} onClick={() => openArtifact(currentRobotArtifact)}><ExternalLink size={13} /></button>}
            </div>
          </article>}
          {cctvVisible && <article className="replay-feed-card">
            <header><span><Camera size={14} />{copy.warehouseFixedCamera}</span><small>{currentFixedArtifact ? virtualCameraLabel(currentFixedArtifact.name, locale) : '—'}</small></header>
            <div className="replay-feed-image">{hasContinuousCctvStream ? <ContinuousVideoFeed
              src={assetUrls[cctvVideoArtifact!.artifact_id]}
              posterUrl={currentFixedArtifact ? assetUrls[currentFixedArtifact.artifact_id] : undefined}
              videoRef={cctvVideoRef}
              alt={copy.warehouseFixedCamera}
              cameraKind="cctv"
              locale={locale}
              playing={playing}
              playbackRate={speed}
              fpsHint={streamManifest?.video_streams?.cctv?.fps || streamManifest?.presentation_fps}
              frameLabel={sharedFrameLabel}
              sourceLabel={locale === 'zh' ? '固定 CCTV / CAM-04 · MP4' : 'FIXED CCTV / CAM-04 · MP4'}
              onEnded={() => setReplayPlaying(false)}
            /> : currentFixedArtifact && assetUrls[currentFixedArtifact.artifact_id] ? <RealtimeCameraFeed
              primaryUrl={assetUrls[currentFixedArtifact.artifact_id]}
              nextUrl={nextStreamCctvArtifact ? assetUrls[nextStreamCctvArtifact.artifact_id] : assetUrls[currentFixedArtifact.artifact_id]}
              alt={copy.warehouseFixedCamera}
              cameraKind="cctv"
              locale={locale}
              playing={playing}
              transitionMs={Math.max(180, (routeFrameDuration * 1000) / speed)}
              frameLabel={sharedFrameLabel}
              sourceLabel={locale === 'zh' ? '固定 CCTV / CAM-04' : 'FIXED CCTV / CAM-04'}
            /> : <span><Camera size={18} />{copy.fixedCameraLoading}</span>}
              {currentFixedArtifact && <button type="button" className="replay-open-evidence" title={copy.openEvidence} aria-label={copy.openEvidence} onClick={() => openArtifact(currentFixedArtifact)}><ExternalLink size={13} /></button>}
            </div>
          </article>}
        </> : <div className="replay-filter-empty"><ShieldAlert size={18} /><strong>{copy.noEvidenceMatch}</strong></div>}
      </div>
    </div>
    {productMode && evidenceMatches && <div className="replay-evidence-panel">
      <div className="replay-evidence-heading"><span><BadgeCheck size={14} />{copy.evidenceWorkbench}</span><strong className={`evidence-state evidence-state-${evidenceStatus}`}><i />{evidenceIsVerified ? copy.evidenceVerified : copy.evidenceAttention}</strong></div>
      <dl className="replay-evidence-grid">
        <div><dt>{copy.evidenceRouteFrame}</dt><dd>#{String(frameRouteIndex).padStart(3, '0')}</dd></div>
        <div><dt>{copy.evidenceRenderFrame}</dt><dd>#{String(frameRenderIndex).padStart(4, '0')}</dd></div>
        <div><dt>{copy.evidenceResolution}</dt><dd>{frameResolution}</dd></div>
        <div><dt>{copy.evidenceSource}</dt><dd>{frameSource}</dd></div>
        <div><dt>{copy.evidenceHash}</dt><dd title={streamRobotArtifact?.sha256}>{streamRobotArtifact ? `RGB ${streamRobotArtifact.sha256.slice(0, 12)}…` : '—'}</dd></div>
        <div><dt>{copy.evidenceHash}</dt><dd title={streamCctvArtifact?.sha256}>{streamCctvArtifact ? `CCTV ${streamCctvArtifact.sha256.slice(0, 12)}…` : '—'}</dd></div>
      </dl>
      <div className="replay-evidence-artifacts"><span><Hash size={12} />{streamRobotArtifact?.name || '—'}</span><span><Hash size={12} />{streamCctvArtifact?.name || '—'}</span></div>
    </div>}
    <div className="replay-controls">
      <div className="replay-control-buttons">
        <button type="button" className="icon-button" title={copy.returnToStart} aria-label={copy.returnToStart} onClick={() => setReplayFrame(0)}><SkipBack size={15} /></button>
        <button type="button" className="primary-button replay-play-button" onClick={() => { if (safeFrameIndex >= maxFrameIndex) setReplayFrame(0, false); setReplayPlaying(!playingRef.current) }} title={playing ? copy.pauseReplay : copy.playReplay}><span aria-hidden="true">{playing ? <Pause size={15} /> : <Play size={15} />}</span>{playing ? copy.pauseReplay : copy.playReplay}</button>
        <button type="button" className="icon-button" title={copy.nextFrame} aria-label={copy.nextFrame} onClick={() => setReplayFrame(nextReplayFrameIndex)}><SkipForward size={15} /></button>
      </div>
      <div className="replay-speed-control"><span>{copy.playbackSpeed}</span>{[0.25, 0.5, 1].map((value) => <button type="button" key={value} className={speed === value ? 'selected' : ''} aria-pressed={speed === value} onClick={() => setSpeed(value)}>{value}x</button>)}</div>
    </div>
    <div className="replay-timeline">
      <div className="replay-timeline-track">
        <input type="range" min="0" max={maxFrameIndex} step="1" value={safeFrameIndex} aria-label={copy.synchronizedReplayProgress} onChange={(event) => setReplayFrame(Number(event.target.value))} />
        <div className="replay-timeline-markers" aria-label={copy.inspectionWaypoint}>
          {waypointFrameIndices.map((frame, index) => <button type="button" className={`replay-timeline-marker${index === currentWaypointIndex ? ' is-current' : ''}`} key={`${waypoints[index]?.waypoint_id || 'waypoint'}-${frame}`} style={{ left: `${maxFrameIndex ? (frame / maxFrameIndex) * 100 : 0}%` }} title={`${waypoints[index]?.waypoint_id || 'WP'} · ${frame}`} aria-label={`${copy.waypoint} ${waypoints[index]?.waypoint_id || index + 1}`} onClick={() => setReplayFrame(frame)}><i /></button>)}
        </div>
      </div>
      <div><span>{replayClock(elapsedSeconds)}</span><span>{replayClock(totalSeconds)}</span></div>
    </div>
    <div className="replay-footnote"><span><Route size={13} />{copy.waypointProgress} {Math.min(currentWaypointIndex + 1, Math.max(waypoints.length, 1))} / {waypoints.length || '—'}</span><span>{currentResult?.assessment?.severity ? `${copy.currentFinding}: ${severityLabel[locale][currentResult.assessment.severity] || currentResult.assessment.severity}` : copy.noFindingAtFrame}</span><span>{sceneInputError ? copy.trajectoryFallback : streamError ? copy.imageStreamFallback : streamManifest?.video_streams ? copy.localBlenderVideoStream : copy.localBlenderStream}</span></div>
  </section>
}

function localizedApi<T>(path: string, token: string, locale: Locale, init?: RequestInit) {
  return api<T>(path, token, locale, init)
}

function localizedHistoryPage<T>(path: string, token: string, locale: Locale) {
  return apiHistoryPage<T>(path, token, locale)
}

function LanguageSwitch({ locale, label, onChange, className = '' }: { locale: Locale; label: string; onChange: (locale: Locale) => void; className?: string }) {
  return <div className={`language-switch ${className}`} role="group" aria-label={label}>
    <button type="button" aria-pressed={locale === 'zh'} className={locale === 'zh' ? 'selected' : ''} onClick={() => onChange('zh')}>中文</button>
    <button type="button" aria-pressed={locale === 'en'} className={locale === 'en' ? 'selected' : ''} onClick={() => onChange('en')}>EN</button>
  </div>
}

function App() {
  const isOverviewRoute = window.location.pathname === '/overview' || window.location.pathname.startsWith('/overview/')
  const isConsoleRoute = !isOverviewRoute
  const [locale, setLocale] = useState<Locale>(() => localStorage.getItem('inspection.locale') === 'en' ? 'en' : 'zh')
  const t = (key: MessageKey) => messages[locale][key]
  const [session, setSession] = useState<Session | null>(null)
  const sessionRoles = rolesFromSession(session)
  const canOperate = sessionRoles.has('admin') || sessionRoles.has('operator')
  const canReview = sessionRoles.has('admin') || sessionRoles.has('reviewer')
  const canSubmitEam = sessionRoles.has('admin')
  const [authReady, setAuthReady] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const [section, setSectionState] = useState<Section>(sectionFromLocation)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [site, setSite] = useState<Site | null>(null)
  const [industrialSite, setIndustrialSite] = useState<IndustrialSiteResponse | null>(null)
  const [waypointsInitialized, setWaypointsInitialized] = useState(false)
  const [missions, setMissions] = useState<Mission[]>([])
  const [latestMissionDetail, setLatestMissionDetail] = useState<MissionDetail | null>(null)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([])
  const [historyCursors, setHistoryCursors] = useState<HistoryCursors>({
    missions: null, workOrders: null, auditEvents: null,
  })
  const [historyLoading, setHistoryLoading] = useState<HistoryLoading>({
    missions: false, workOrders: false, auditEvents: false,
  })
  const loadedMoreHistory = useRef<Record<HistoryCollection, boolean>>({
    missions: false, workOrders: false, auditEvents: false,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [accessDenied, setAccessDenied] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [selectedWaypoints, setSelectedWaypoints] = useState<string[]>([])
  const [seed, setSeed] = useState(42)
  const [renderVirtualWorld, setRenderVirtualWorld] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedMission, setSelectedMission] = useState<Mission | null>(null)
  const detailRequestId = useRef(0)
  const [missionDetail, setMissionDetail] = useState<MissionDetail | null>(null)
  const [missionArtifacts, setMissionArtifacts] = useState<Artifact[]>([])
  const [artifactLoading, setArtifactLoading] = useState(false)
  const [artifactError, setArtifactError] = useState('')
  const [downloadingArtifact, setDownloadingArtifact] = useState<string | null>(null)
  const [reviewDraft, setReviewDraft] = useState<Record<string, string>>({})
  const [submittingEam, setSubmittingEam] = useState<Record<string, boolean>>({})
  const [missionQuery, setMissionQuery] = useState('')
  const [missionFilter, setMissionFilter] = useState<MissionFilter>('all')
  const [lastSynced, setLastSynced] = useState<Date | null>(null)
  const [currentClock, setCurrentClock] = useState(() => new Date())
  const refreshRequestId = useRef(0)
  const [pendingMissionKeys] = useState<PendingMissionKeys>(readPendingMissionKeys)
  const lastFocusedElementRef = useRef<HTMLElement | null>(null)

  const setSection = useCallback((next: Section) => {
    setSectionState(next)
    if (typeof window === 'undefined') return
    const url = new URL(window.location.href)
    if (next === 'missions') url.searchParams.delete('view')
    else url.searchParams.set('view', next)
    const query = url.searchParams.toString()
    window.history.pushState({ ...(window.history.state || {}), view: next }, '', `${url.pathname}${query ? `?${query}` : ''}${url.hash}`)
  }, [])

  useEffect(() => {
    const syncSectionFromHistory = () => setSectionState(sectionFromLocation())
    window.addEventListener('popstate', syncSectionFromHistory)
    return () => window.removeEventListener('popstate', syncSectionFromHistory)
  }, [])

  useEffect(() => {
    localStorage.setItem('inspection.locale', locale)
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
    document.title = isConsoleRoute
      ? t('pageTitle')
      : locale === 'zh' ? '工业巡检平台 | 项目总览' : 'Industrial Inspection Platform | Overview'
  }, [locale, isConsoleRoute])

  useEffect(() => {
    const timer = window.setInterval(() => setCurrentClock(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const focusMissionSearch = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k'
        || document.querySelector('.modal-backdrop')) return
      const input = document.querySelector<HTMLInputElement>('.table-search input')
      if (!input) return
      event.preventDefault()
      input.focus()
      input.select()
    }
    window.addEventListener('keydown', focusMissionSearch)
    return () => window.removeEventListener('keydown', focusMissionSearch)
  }, [])

  useEffect(() => {
    if (localDemoMode) {
      setSession(localDemoSession)
      setAccessDenied(false)
      setAuthReady(true)
      return
    }
    if (!supabase) { setAuthReady(true); return }
    let mounted = true
    let authEventVersion = 0
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => {
      authEventVersion += 1
      if (!mounted) return
      setSession(next)
      setAccessDenied(false)
      setError('')
      setAuthError('')
      setAuthReady(true)
    })
    const initialEventVersion = authEventVersion
    void supabase.auth.getSession()
      .then(({ data, error: sessionError }) => {
        if (!mounted || authEventVersion !== initialEventVersion) return
        if (sessionError) {
          setSession(null)
          setAuthError(t('authRequestFailed'))
          return
        }
        setSession(data.session)
      })
      .catch(() => {
        if (!mounted || authEventVersion !== initialEventVersion) return
        setSession(null)
        setAuthError(t('authRequestFailed'))
      })
      .finally(() => {
        if (mounted) setAuthReady(true)
      })
    return () => {
      mounted = false
      listener.subscription.unsubscribe()
    }
  }, [])

  const refresh = useCallback(async () => {
    const token = session?.access_token
    if (!token || accessDenied) return
    const requestId = ++refreshRequestId.current
    setLoading(true)
    setError('')
    try {
      const [nextDashboard, nextSite, nextMissions, nextOrders, nextIndustrialSite] = await Promise.all([
        localizedApi<Dashboard>('/dashboard', token, locale), localizedApi<Site>('/sites', token, locale),
        localizedHistoryPage<Mission>('/missions?limit=50', token, locale),
        localizedHistoryPage<WorkOrder>('/work-orders?limit=50', token, locale),
        localizedApi<IndustrialSiteResponse>('/industrial/site', token, locale).catch(() => null),
      ])
      let latestDetail: MissionDetail | null = null
      if (nextMissions.items[0]) {
        try {
          latestDetail = await localizedApi<MissionDetail>(`/missions/${nextMissions.items[0].run_id}`, token, locale)
        } catch {
          latestDetail = null
        }
      }
      if (requestId !== refreshRequestId.current) return
      setDashboard(nextDashboard)
      setSite(nextSite)
      setIndustrialSite(nextIndustrialSite)
      setMissions((current) => mergeHistory(nextMissions.items, current, (mission) => mission.run_id))
      setSelectedMission((current) => current
        ? nextMissions.items.find((mission) => mission.run_id === current.run_id) || current
        : current)
      setLatestMissionDetail(latestDetail)
      setWorkOrders((current) => mergeHistory(nextOrders.items, current, (order) => order.ticket_id))
      setHistoryCursors((current) => ({
        missions: loadedMoreHistory.current.missions ? current.missions : nextMissions.nextCursor,
        workOrders: loadedMoreHistory.current.workOrders ? current.workOrders : nextOrders.nextCursor,
        auditEvents: current.auditEvents,
      }))
      setLastSynced(new Date())
      if (!waypointsInitialized) {
        setSelectedWaypoints(nextSite.waypoints.map((item) => item.waypoint_id))
        setWaypointsInitialized(true)
      }
      if (section === 'audit') {
        const nextAudit = await localizedHistoryPage<AuditEvent>('/audit-events?limit=50', token, locale)
        if (requestId !== refreshRequestId.current) return
        setAuditEvents((current) => mergeHistory(nextAudit.items, current, (event) => event.event_id))
        setHistoryCursors((current) => ({
          ...current,
          auditEvents: loadedMoreHistory.current.auditEvents ? current.auditEvents : nextAudit.nextCursor,
        }))
      }
    } catch (reason) {
      if (requestId === refreshRequestId.current) {
        if (reason instanceof ApiError && reason.code === 'APPLICATION_ROLE_REQUIRED') {
          setAccessDenied(true)
          setError('')
        } else {
          setError(reason instanceof Error ? reason.message : t('loadFailed'))
        }
      }
    } finally {
      if (requestId === refreshRequestId.current) setLoading(false)
    }
  }, [session?.access_token, section, waypointsInitialized, locale, accessDenied])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!session || accessDenied) return
    const timer = window.setInterval(() => { void refresh() }, 8000)
    return () => window.clearInterval(timer)
  }, [session, refresh, accessDenied])
  useEffect(() => {
    if (!authReady || !session || accessDenied || canReview || section !== 'audit') return
    setAuditEvents([])
    loadedMoreHistory.current.auditEvents = false
    setHistoryCursors((current) => ({ ...current, auditEvents: null }))
    setSection('missions')
  }, [accessDenied, authReady, canReview, section, session])

  const [hoveredWaypointId, setHoveredWaypointId] = useState<string | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!session || accessDenied) return
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (section !== 'missions') setSection('missions')
        window.requestAnimationFrame(() => {
          searchInputRef.current?.focus()
          searchInputRef.current?.select()
        })
        return
      }
      if (event.key === 'Escape') {
        if (showCreate) {
          setShowCreate(false)
        } else if (selectedMission) {
          closeMissionDetails()
        } else if (document.activeElement === searchInputRef.current && missionQuery) {
          setMissionQuery('')
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [accessDenied, missionQuery, section, selectedMission, session, showCreate])

  useLayoutEffect(() => {
    if (!showCreate && !selectedMission) {
      const previous = lastFocusedElementRef.current
      lastFocusedElementRef.current = null
      if (previous && document.contains(previous)) previous.focus()
      return
    }
    if (!lastFocusedElementRef.current) {
      const active = document.activeElement
      lastFocusedElementRef.current = active instanceof HTMLElement ? active : null
    }
    const selector = selectedMission
      ? '.detail-panel .modal-header .icon-button'
      : '.modal:not(.detail-panel) .modal-header .icon-button'
    document.querySelector<HTMLButtonElement>(selector)?.focus()
  }, [selectedMission, showCreate])

  useEffect(() => {
    if (!showCreate && !selectedMission) return
    const getFocusableElements = (dialog: HTMLElement) => Array.from(dialog.querySelectorAll<HTMLElement>([
      'a[href]',
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(','))).filter((element) => element.getAttribute('aria-hidden') !== 'true' && element.offsetParent !== null)
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const dialog = document.querySelector<HTMLElement>('[role="dialog"][aria-modal="true"]')
      if (!dialog) return
      const focusable = getFocusableElements(dialog)
      if (!focusable.length) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
      const activeIndex = active ? focusable.indexOf(active) : -1
      if (!dialog.contains(active) || activeIndex === -1) {
        event.preventDefault()
        event.stopPropagation()
        const target = event.shiftKey ? last : first
        target.focus()
      } else if (event.shiftKey && activeIndex === 0) {
        event.preventDefault()
        event.stopPropagation()
        last.focus()
      } else if (!event.shiftKey && activeIndex === focusable.length - 1) {
        event.preventDefault()
        event.stopPropagation()
        first.focus()
      }
    }
    document.addEventListener('keydown', trapFocus, true)
    return () => document.removeEventListener('keydown', trapFocus, true)
  }, [selectedMission, showCreate])

  const counts = dashboard?.mission_counts || {}
  const activeCount = useMemo(() => ['QUEUED', 'SUBMITTING', 'SUBMITTED', 'PENDING', 'RUNNING', 'CANCELLING', 'IMPORTING'].reduce((sum, key) => sum + (counts[key] || 0), 0), [counts])
  const attentionCount = ['PARTIAL', 'FAILED', 'TIMED_OUT', 'RESULT_IMPORT_FAILED'].reduce((sum, key) => sum + (counts[key] || 0), 0)
  const missionCount = Object.values(counts).reduce((sum, count) => sum + count, 0)
  const pendingOrders = workOrders.filter((item) => item.review_status === 'PENDING')
  const siteMapPoints = useMemo(() => layoutWaypoints(site?.waypoints || []), [site])
  const siteRoutePolyline = useMemo(() => {
    if (siteMapPoints.length < 2) return siteMapPoints
    const points = siteMapPoints.map(({ x, y }) => ({ x, y }))
    const route = [points[0]]
    for (let index = 1; index < points.length; index += 1) {
      const previous = route[route.length - 1]
      const target = points[index]
      const elbow = Math.abs(target.x - previous.x) >= Math.abs(target.y - previous.y)
        ? { x: target.x, y: previous.y }
        : { x: previous.x, y: target.y }
      if (Math.hypot(elbow.x - previous.x, elbow.y - previous.y) > 1) route.push(elbow)
      route.push(target)
    }
    return route
  }, [siteMapPoints])
  const sceneRoutePlan = useMemo(() => buildCollisionSafeRoute((site?.waypoints || []).map((waypoint) => ({
    waypoint_id: waypoint.waypoint_id,
    position: waypoint.position,
  }))), [site])
  const latestResults = useMemo(() => new Map(
    (latestMissionDetail?.result?.results || []).map((result) => [result.waypoint_id, result]),
  ), [latestMissionDetail])
  const latestObservedCount = [...latestResults.values()].filter((result) => result.observation).length
  const latestFindingCount = [...latestResults.values()].reduce(
    (count, result) => count + (result.assessment?.anomalies.length || 0), 0,
  )
  const visibleMissions = useMemo(() => {
    const query = missionQuery.trim().toLowerCase()
    return missions.filter((mission) => {
      const matchesQuery = !query || [mission.run_id, mission.site_id, mission.robot_id, mission.slurm_job_id || '']
        .some((value) => value.toLowerCase().includes(query))
      const matchesFilter = missionFilter === 'all'
        || (missionFilter === 'active' && ['QUEUED', 'SUBMITTING', 'SUBMITTED', 'PENDING', 'RUNNING', 'CANCELLING', 'IMPORTING'].includes(mission.status))
        || (missionFilter === 'attention' && ['PARTIAL', 'FAILED', 'TIMED_OUT', 'RESULT_IMPORT_FAILED'].includes(mission.status))
        || (missionFilter === 'completed' && ['SUCCEEDED', 'CANCELLED'].includes(mission.status))
      return matchesQuery && matchesFilter
    })
  }, [missionFilter, missionQuery, missions])

  async function loadMoreHistory(collection: HistoryCollection) {
    const cursor = historyCursors[collection]
    if (!session || !cursor || historyLoading[collection]) return
    setHistoryLoading((current) => ({ ...current, [collection]: true }))
    try {
      const limits: Record<HistoryCollection, number> = {
        missions: 50, workOrders: 50, auditEvents: 50,
      }
      const endpoint: Record<HistoryCollection, string> = {
        missions: '/missions', workOrders: '/work-orders', auditEvents: '/audit-events',
      }
      const query = new URLSearchParams({ limit: String(limits[collection]), cursor })
      if (collection === 'missions') {
        const page = await localizedHistoryPage<Mission>(`${endpoint[collection]}?${query}`, session.access_token, locale)
        setMissions((current) => mergeHistory(current, page.items, (mission) => mission.run_id))
        setHistoryCursors((current) => ({ ...current, missions: page.nextCursor }))
      } else if (collection === 'workOrders') {
        const page = await localizedHistoryPage<WorkOrder>(`${endpoint[collection]}?${query}`, session.access_token, locale)
        setWorkOrders((current) => mergeHistory(current, page.items, (order) => order.ticket_id))
        setHistoryCursors((current) => ({ ...current, workOrders: page.nextCursor }))
      } else {
        const page = await localizedHistoryPage<AuditEvent>(`${endpoint[collection]}?${query}`, session.access_token, locale)
        setAuditEvents((current) => mergeHistory(current, page.items, (event) => event.event_id))
        setHistoryCursors((current) => ({ ...current, auditEvents: page.nextCursor }))
      }
      loadedMoreHistory.current[collection] = true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('loadFailed'))
    } finally {
      setHistoryLoading((current) => ({ ...current, [collection]: false }))
    }
  }

  async function signIn(event: React.FormEvent) {
    event.preventDefault()
    if (!supabase) return
    setAuthError('')
    setSigningIn(true)
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({ email, password })
      if (signInError) {
        const authMessages: Record<string, MessageKey> = {
          'Invalid login credentials': 'invalidCredentials',
          'Email not confirmed': 'emailNotConfirmed',
        }
        setAuthError(authMessages[signInError.message] ? t(authMessages[signInError.message]) : signInError.message)
      }
    } catch {
      setAuthError(t('authRequestFailed'))
    } finally { setSigningIn(false) }
  }

  async function createMission(event: React.FormEvent) {
    event.preventDefault()
    if (!canOperate || !session || !site || selectedWaypoints.length === 0) return
    setSubmitting(true)
    setError('')
    const request = {
      site_id: site.site_id,
      waypoint_ids: selectedWaypoints,
      seed,
      ...(renderVirtualWorld ? { render_backend: 'blender' } : {}),
    }
    const fingerprint = JSON.stringify({ user_id: session.user.id, request })
    const idempotencyKey = pendingMissionKeys[fingerprint] || crypto.randomUUID()
    pendingMissionKeys[fingerprint] = idempotencyKey
    writePendingMissionKeys(pendingMissionKeys)
    try {
      await localizedApi<Mission>('/missions', session.access_token, locale, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify(request),
      })
      delete pendingMissionKeys[fingerprint]
      writePendingMissionKeys(pendingMissionKeys)
      setShowCreate(false)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('createFailed'))
    } finally { setSubmitting(false) }
  }

  async function openMission(mission: Mission) {
    if (!session) return
    const requestId = ++detailRequestId.current
    setSelectedMission(mission)
    setMissionDetail(null)
    setMissionArtifacts([])
    setArtifactError('')
    setArtifactLoading(true)
    try {
      const detail = await localizedApi<MissionDetail>(`/missions/${mission.run_id}`, session.access_token, locale)
      if (requestId !== detailRequestId.current) return
      setMissionDetail(detail)
      try {
        const artifacts = await localizedApi<Artifact[]>(`/missions/${mission.run_id}/artifacts`, session.access_token, locale)
        if (requestId === detailRequestId.current) setMissionArtifacts(artifacts)
      } catch {
        if (requestId === detailRequestId.current) setArtifactError(t('artifactLoadFailed'))
      }
    }
    catch (reason) {
      if (requestId === detailRequestId.current) setError(reason instanceof Error ? reason.message : t('missionReadFailed'))
    } finally {
      if (requestId === detailRequestId.current) setArtifactLoading(false)
    }
  }

  function closeMissionDetails() {
    detailRequestId.current += 1
    setSelectedMission(null)
    setMissionDetail(null)
    setMissionArtifacts([])
  }

  async function downloadArtifact(artifact: Artifact) {
    if (!session) return
    setDownloadingArtifact(artifact.artifact_id)
    setArtifactError('')
    try {
      const response = await fetch(`${apiBase}/artifacts/${artifact.artifact_id}`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      })
      if (!response.ok) throw new Error(`${t('downloadFailed')} (${response.status})`)
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = artifact.name
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) {
      setArtifactError(reason instanceof Error ? reason.message : t('downloadFailed'))
    } finally { setDownloadingArtifact(null) }
  }

  async function cancelMission(mission: Mission) {
    if (!canOperate || !session || !window.confirm(`${t('cancelMissionConfirm')} ${mission.run_id}?`)) return
    try {
      const updated = await localizedApi<Mission>(`/missions/${mission.run_id}/cancel`, session.access_token, locale, { method: 'POST' })
      setSelectedMission(updated)
      closeMissionDetails()
      await refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('cancelFailed')) }
  }

  async function reviewOrder(order: WorkOrder, decision: 'ACKNOWLEDGED' | 'DISMISSED') {
    if (!canReview || !session) return
    const comment = (reviewDraft[order.ticket_id] || '').trim()
    if (comment.length < 3) { setError(t('reviewCommentMin')); return }
    try {
      const result = await localizedApi<Pick<WorkOrder, 'ticket_id' | 'review_status' | 'reviewed_by' | 'reviewed_at'>>(`/work-orders/${order.ticket_id}/review`, session.access_token, locale, {
        method: 'POST', body: JSON.stringify({ decision, comment }),
      })
      setWorkOrders((current) => current.map((item) => item.ticket_id === order.ticket_id
        ? {
          ...item,
          review_status: result.review_status,
          reviewed_by: result.reviewed_by,
          review_decision: decision,
          review_comment: comment,
          reviewed_at: result.reviewed_at,
        }
        : item))
      if (order.review_status === 'PENDING') {
        setDashboard((current) => current ? {
          ...current,
          pending_work_orders: Math.max(0, current.pending_work_orders - 1),
        } : current)
      }
      setReviewDraft((current) => ({ ...current, [order.ticket_id]: '' }))
      await refresh()
    } catch (reason) { setError(reason instanceof Error ? reason.message : t('reviewFailed')) }
  }

  async function submitEam(order: WorkOrder) {
    if (!canSubmitEam || !session || order.review_status !== 'REVIEWED'
      || order.review_decision !== 'ACKNOWLEDGED') return
    setSubmittingEam((current) => ({ ...current, [order.ticket_id]: true }))
    setError('')
    try {
      const result = await localizedApi<{
        ticket_id: string; status: EamSubmission['status']; external_id: string | null
        idempotent_replay: boolean
      }>(`/work-orders/${order.ticket_id}/eam`, session.access_token, locale, { method: 'POST' })
      setWorkOrders((current) => current.map((item) => item.ticket_id === order.ticket_id
        ? {
          ...item,
          eam_submission: {
            status: result.status,
            attempts: (item.eam_submission?.attempts || 0) + (result.idempotent_replay ? 0 : 1),
            external_id: result.external_id,
            submitted_at: item.eam_submission?.submitted_at || new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        }
        : item))
      await refresh()
    } catch (reason) {
      await refresh()
      setError(reason instanceof Error ? reason.message : t('eamFailed'))
    } finally {
      setSubmittingEam((current) => ({ ...current, [order.ticket_id]: false }))
    }
  }

  const selectedOrders = selectedMission
    ? workOrders.filter((order) => order.run_id === selectedMission.run_id)
    : []
  const virtualSceneGlb = missionArtifacts.find((artifact) => artifact.name === 'factory_scene.glb')
  const virtualSceneCameras = missionArtifacts.filter((artifact) => artifact.name.endsWith('.png') && (
    artifact.name.startsWith('factory_') || artifact.name.startsWith('virtual_world__')
  )).sort((left, right) => virtualCameraRank(left.name) - virtualCameraRank(right.name)
    || left.name.localeCompare(right.name))
  const replayHasArtifacts = missionArtifacts.some((artifact) => artifact.name === 'scene_input.json'
    || artifact.name === 'trajectory.json'
    || artifact.name === 'synchronized_video_manifest.json'
    || (artifact.name.startsWith('virtual_world__') && artifact.name.endsWith('__rgb_camera.png'))
    || (artifact.name.startsWith('factory_cctv__') && artifact.name.endsWith('.png'))
    || artifact.name === 'factory_overview.png'
    || /^factory_orbit_\d+\.png$/.test(artifact.name))
  const selectedStatus = selectedMission?.status || ''
  const executionState = selectedStatus === 'QUEUED' ? 'waiting'
    : ['SUBMITTING', 'SUBMITTED', 'PENDING', 'RUNNING', 'CANCELLING'].includes(selectedStatus) ? 'active'
      : ['FAILED', 'TIMED_OUT', 'CANCELLED'].includes(selectedStatus) ? 'failed' : 'complete'
  const resultState = selectedStatus === 'IMPORTING' ? 'active'
    : selectedStatus === 'RESULT_IMPORT_FAILED' ? 'failed'
      : missionDetail?.result ? 'complete' : 'waiting'
  const reviewState = selectedOrders.some((order) => order.review_status === 'PENDING') ? 'active'
    : missionDetail?.result ? 'complete' : 'waiting'
  const traceStateLabel: Record<string, string> = {
    waiting: t('traceWaiting'), active: t('traceActive'), complete: t('traceComplete'), failed: t('traceFailed'),
  }

  if (!isConsoleRoute) return <ProjectHome locale={locale} onLocaleChange={setLocale} />
  if (!authReady) return <div className="boot-state"><Activity size={18} />{t('booting')}</div>
  if (!session) {
    return <main className="login-screen">
      <section className="login-panel">
        <div className="login-brand-row"><div className="login-brand"><span className="brand-mark"><Factory size={16} /></span><span className="brand-type"><strong>{t('brand')}</strong><small>{t('brandContext')}</small></span></div><LanguageSwitch locale={locale} label={t('language')} onChange={setLocale} /></div>
        <div className="login-heading"><h1>{t('loginTitle')}</h1><p className="login-copy">{t('loginCopy')}</p></div>
        {!supabase ? <div className="notice error-notice">{t('authConfigMissing')}</div> : <form onSubmit={signIn} className="login-form">
          <label>{t('email')}<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>{t('password')}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {authError && <p className="form-error" role="alert">{authError}</p>}
          <button className="primary-button login-button" type="submit" disabled={signingIn} aria-busy={signingIn}>{signingIn ? t('signInProgress') : t('signIn')} <ArrowRight size={16} /></button>
        </form>}
        <p className="login-foot"><ShieldCheck size={14} />{t('accountPolicy')}</p>
      </section>
      <aside className="login-aside">
        <div className="login-aside-head"><span><b>01</b>{t('brandContext')}</span><span className="simulation-tag"><i />{t('simulationPreview')}</span></div>
        <div className="aside-copy">
          <h2>{t('workflowHeadline')}</h2>
          <p>{t('workflowCopy')}</p>
          <ol className="login-capabilities" aria-label={t('operationsCenter')}>
            {loginModules.map((module, index) => <li key={module.title}><span className="capability-index">{String(index + 1).padStart(2, '0')}</span><strong>{t(module.title)}</strong><span>{t(module.description)}</span></li>)}
          </ol>
        </div>
        <div className="login-aside-foot">{t('simulationOnly')}</div>
      </aside>
    </main>
  }

  if (accessDenied) {
    return <main className="access-denied-screen">
      <section className="access-denied-panel">
        <div className="login-brand-row">
          <div className="login-brand"><span className="brand-mark"><Factory size={16} /></span><span className="brand-type"><strong>{t('brand')}</strong><small>{t('brandContext')}</small></span></div>
          <LanguageSwitch locale={locale} label={t('language')} onChange={setLocale} />
        </div>
        <div className="access-denied-content">
          <span className="access-denied-icon"><ShieldAlert size={21} /></span>
          <span className="access-denied-label">{t('accessDeniedLabel')}</span>
          <h1>{t('accountRoleRequired')}</h1>
          <p>{t('accountRoleExplanation')}</p>
          <div className="access-denied-account"><span className="avatar">{session.user.email?.slice(0, 1).toUpperCase()}</span><span><small>{t('signedInAs')}</small><strong>{session.user.email}</strong></span></div>
          <button className="secondary-button access-denied-signout" type="button" onClick={() => void supabase?.auth.signOut()}><LogOut size={15} />{t('signOut')}</button>
          <p className="login-foot"><ShieldCheck size={14} />{t('sessionVerified')}</p>
        </div>
      </section>
      <aside className="access-denied-aside">
        <div className="access-denied-aside-copy"><span>{t('brandContext')}</span><h2>{t('workflowHeadline')}</h2><p>{t('workflowCopy')}</p></div>
        <div className="login-aside-foot">{t('simulationOnly')}</div>
      </aside>
    </main>
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="sidebar-brand"><span className="brand-mark"><Factory size={16} /></span><span className="brand-type"><strong>{t('brand')}</strong><small>{t('brandContext')}</small></span></div>
      <div className="sidebar-site"><span>{t('currentSite')}</span><strong>{siteNameLabel(dashboard?.site.site_name, locale) || t('loading')}</strong><small>{dashboard?.site.site_id || '—'}</small></div>
      <nav className="main-nav" aria-label={t('operationsCenter')}>
        <div className="nav-group"><span className="nav-group-label">{t('navOperations')}</span>
          <button aria-current={section === 'missions' ? 'page' : undefined} className={section === 'missions' ? 'nav-item active' : 'nav-item'} onClick={() => setSection('missions')}><Activity size={17} />{t('missions')}<span className="nav-count">{missionCount}</span></button>
        </div>
        <div className="nav-group"><span className="nav-group-label">{t('navSimulation')}</span>
          <button aria-current={section === 'simulation' ? 'page' : undefined} className={section === 'simulation' ? 'nav-item active' : 'nav-item'} onClick={() => setSection('simulation')}><MapPin size={17} />{t('simulationSection')}<span className="nav-count">{site?.waypoints.length || 0}</span></button>
        </div>
        <div className="nav-group"><span className="nav-group-label">{t('navPerception')}</span>
          <button aria-current={section === 'diagnostics' ? 'page' : undefined} className={section === 'diagnostics' ? 'nav-item active' : 'nav-item'} onClick={() => setSection('diagnostics')}><Activity size={17} />{t('diagnosticsSection')}<span className="nav-count alert-count">{latestFindingCount}</span></button>
        </div>
        <div className="nav-group"><span className="nav-group-label">{t('navCloseout')}</span>
          <button aria-current={section === 'work-orders' ? 'page' : undefined} className={section === 'work-orders' ? 'nav-item active' : 'nav-item'} onClick={() => setSection('work-orders')}><ClipboardCheck size={17} />{t('workOrders')}<span className="nav-count alert-count">{dashboard?.pending_work_orders ?? 0}</span></button>
          {canReview && <button aria-current={section === 'audit' ? 'page' : undefined} className={section === 'audit' ? 'nav-item active' : 'nav-item'} onClick={() => setSection('audit')}><FileSearch size={17} />{t('audit')}</button>}
        </div>
      </nav>
      <div className="sidebar-bottom">
        <div className="cabinet-status" aria-label={t('cabinetStatus')}>
          <div className={`cabinet-status-row cabinet-status-${workerStatusTone[dashboard?.worker.status || 'not_seen'] || 'muted'}`}><span><i />{t('workerHeartbeat')}</span><strong>{workerStatusLabel[locale][dashboard?.worker.status || 'not_seen'] || workerStatusLabel[locale].not_seen}</strong></div>
          <div className={`cabinet-status-row cabinet-status-${session ? 'nominal' : 'muted'}`}><span><i />{t('databaseStatus')}</span><strong>{session ? t('connected') : t('waitingSync')}</strong></div>
          <div className={`cabinet-status-row cabinet-status-${dashboard?.eam_enabled ? 'nominal' : 'advisory'}`}><span><i />{t('eamAdapter')}</span><strong>{dashboard?.eam_enabled ? t('connected') : t('eamDisconnected')}</strong></div>
        </div>
        <div className="sidebar-auth-line"><span className="service-dot" />{t('apiAuthenticated')}</div>
        <div className="user-row"><span className="avatar">{session.user.email?.slice(0, 1).toUpperCase()}</span><span className="user-email">{session.user.email}</span><button className="icon-button signout" title={t('signOut')} aria-label={t('signOut')} onClick={() => void supabase?.auth.signOut()}><LogOut size={16} /></button></div>
      </div>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="topbar-title">
          <span className="topbar-kicker">{t('controlDesk')}</span>
          <h1>{section === 'missions' ? t('siteOverview') : section === 'simulation' ? t('simulationSection') : section === 'diagnostics' ? t('diagnosticsSection') : section === 'work-orders' ? t('workOrderReview') : t('audit')}</h1>
          <span className="topbar-context">{siteNameLabel(dashboard?.site.site_name, locale) || t('siteOverview')} <i /> {dashboard?.execution_backend === 'slurm' ? t('slurmCluster') : t('offlineEnvironment')}</span>
        </div>
        <div className="top-operational-ribbon" aria-label={t('controlDesk')}>
          <span><small>{t('currentSite')}</small><strong>{dashboard?.site.site_id || 'SITE-—'}</strong></span>
          <span><small>{t('currentClock')}</small><strong>{new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(currentClock)}</strong></span>
          <span><small>{t('executionMode')}</small><strong>{dashboard?.execution_backend === 'slurm' ? t('slurmCluster') : t('simulated')}</strong></span>
          <span><small>{t('eamAdapter')}</small><strong className={dashboard?.eam_enabled ? 'ribbon-nominal' : 'ribbon-advisory'}>{dashboard?.eam_enabled ? t('connected') : t('eamDisconnected')}</strong></span>
        </div>
        <div className="top-actions">
          <LanguageSwitch locale={locale} label={t('language')} onChange={setLocale} />
          <span className={`worker-health worker-health-${workerStatusTone[dashboard?.worker.status || 'not_seen'] || 'muted'}`} role="status">
            <i />{workerStatusLabel[locale][dashboard?.worker.status || 'not_seen'] || workerStatusLabel[locale].not_seen}
          </span>
          <span className="sync-label"><span className="service-dot" />{lastSynced ? `${t('syncedAt')} ${new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(lastSynced)}` : t('waitingSync')}</span>
          <button className="icon-button" title={t('refreshData')} aria-label={t('refreshData')} onClick={() => void refresh()} disabled={loading}><RefreshCw size={17} className={loading ? 'spinning' : ''} /></button>
          <button className="mobile-account" title={t('signOut')} aria-label={t('signOut')} onClick={() => void supabase?.auth.signOut()}><LogOut size={16} /></button>
          {canOperate && ['missions', 'simulation'].includes(section) && <button className="primary-button" title={t('createInspection')} aria-label={t('createInspection')} onClick={() => setShowCreate(true)}><Plus size={17} />{t('createInspection')}</button>}
        </div>
      </header>

      {error && <div className="notice error-notice page-notice"><AlertTriangle size={16} />{error}<button className="icon-button" title={t('closeNotice')} aria-label={t('closeNotice')} onClick={() => setError('')}><X size={15} /></button></div>}

      {section === 'simulation' && <section className="module-intro">
        <div><span className="eyebrow">{dashboard?.site.site_id || t('currentSite')}</span><p>{t('scenePageCopy')}</p></div>
        <span className="source-flag"><i />{dashboard?.execution_backend === 'slurm' ? t('slurmCluster') : t('offlineEnvironment')}</span>
      </section>}

      {['missions', 'simulation'].includes(section) && <>
        {section === 'missions' && <>
        <section className="workflow-section" aria-label={t('overview')}>
          <div className="summary-strip" aria-label={t('overview')}>
            <div className="summary-item metric-active"><span>{t('phaseCreated')}</span><strong>{dashboard ? missionCount : '—'}</strong><small>{t('missionRecords')}</small><div className="summary-meter"><i style={{ width: dashboard ? `${missionCount ? Math.min(100, Math.max(16, Math.round((missionCount / Math.max(missionCount, 8)) * 100))) : 0}%` : '0%' }} /></div></div>
            <div className="summary-item metric-running"><span>{t('phaseExecution')}</span><strong>{dashboard ? activeCount : '—'}</strong><small>{t('activeMissions')}</small><div className="summary-meter"><i style={{ width: dashboard ? `${missionCount ? Math.min(100, Math.round((activeCount / Math.max(missionCount, 1)) * 100)) : 0}%` : '0%' }} /></div></div>
            <div className="summary-item metric-complete"><span>{t('phaseResults')}</span><strong>{dashboard ? (counts.SUCCEEDED || 0) + (counts.PARTIAL || 0) : '—'}</strong><small>{t('resultsValidated')}</small><div className="summary-meter"><i style={{ width: dashboard ? `${missionCount ? Math.min(100, Math.round((((counts.SUCCEEDED || 0) + (counts.PARTIAL || 0)) / Math.max(missionCount, 1)) * 100)) : 0}%` : '0%' }} /></div></div>
            <div className="summary-item metric-review"><span>{t('phaseReview')}</span><strong>{dashboard?.pending_work_orders ?? '—'}</strong><small>{t('needsConfirmation')}</small><div className="summary-meter"><i style={{ width: dashboard ? `${workOrders.length ? Math.min(100, Math.round(((dashboard.pending_work_orders || 0) / Math.max(workOrders.length, 1)) * 100)) : (dashboard.pending_work_orders ? 100 : 0)}%` : '0%' }} /></div></div>
          </div>
        </section>
        </>}
        <section className="site-overview" aria-label={t('siteOverview')}>
          <div className="site-panel site-map-panel">
            <div className="site-panel-heading"><div><span className="eyebrow">{t('currentSite')}</span><h2>{siteNameLabel(dashboard?.site.site_name, locale) || t('loading')}</h2></div><span className="source-flag"><i />{dashboard?.execution_backend === 'slurm' ? t('slurmCluster') : t('offlineEnvironment')}</span></div>
            <div className="site-map-canvas">
              {siteMapPoints.length > 0 ? <svg className="site-map-svg" viewBox="0 0 640 300" role="img" aria-label={t('sitePoints')}>
                <title>{t('sitePoints')}</title>
                <rect className="site-map-frame" x="28" y="20" width="584" height="256" rx="3" />
                {hoveredWaypointId && (() => {
                  const target = siteMapPoints.find((entry) => entry.waypoint.waypoint_id === hoveredWaypointId)
                  if (!target) return null
                  return <g className="site-map-crosshairs" aria-hidden="true">
                    <line x1="28" y1={target.y} x2="612" y2={target.y} />
                    <line x1={target.x} y1="20" x2={target.x} y2="276" />
                  </g>
                })()}
                {siteRoutePolyline.length > 1 && <polyline className="site-route-line" data-route-planner="orthogonal-service-lanes" points={siteRoutePolyline.map((point) => `${point.x},${point.y}`).join(' ')} />}
                {siteMapPoints.map(({ waypoint, index, x, y }) => {
                  const result = latestResults.get(waypoint.waypoint_id)
                  const severity = result?.assessment?.severity?.toLowerCase() || 'unknown'
                  const isHovered = hoveredWaypointId === waypoint.waypoint_id
                  return <g
                    className={`map-point map-point-${severity}${isHovered ? ' is-hovered' : ''}`}
                    key={waypoint.waypoint_id}
                    onPointerEnter={() => setHoveredWaypointId(waypoint.waypoint_id)}
                    onPointerLeave={() => setHoveredWaypointId((current) => current === waypoint.waypoint_id ? null : current)}
                  >
                    <circle className="map-point-halo" cx={x} cy={y} r="17" />
                    <circle className="map-point-core" cx={x} cy={y} r="11.5" />
                    <text x={x} y={y + 3.5}>{String(index + 1).padStart(2, '0')}</text>
                  </g>
                })}
              </svg> : <div className="map-empty"><MapPin size={19} /><span>{t('mapUnavailable')}</span></div>}
              <span className="map-axis map-axis-x">X / m</span><span className="map-axis map-axis-y">Y / m</span>
            </div>
            <div className="map-caption"><span><i className="route-key" />{t('mapLegend')}</span><span>{t('mapCaption')}</span></div>
            <div className="site-waypoint-heading"><span>{t('sitePoints')}</span><span>{t('latestReadings')}</span></div>
            <div className="site-waypoint-list">
              {site?.waypoints.map((waypoint, index) => {
                const result = latestResults.get(waypoint.waypoint_id)
                const observation = result?.observation
                const severity = result?.assessment?.severity || 'UNKNOWN'
                const isHovered = hoveredWaypointId === waypoint.waypoint_id
                return <button className={`site-waypoint-row${isHovered ? ' is-hovered' : ''}`} key={waypoint.waypoint_id} type="button"
                  disabled={!missions[0]}
                  onPointerEnter={() => setHoveredWaypointId(waypoint.waypoint_id)}
                  onPointerLeave={() => setHoveredWaypointId((current) => current === waypoint.waypoint_id ? null : current)}
                  onFocus={() => setHoveredWaypointId(waypoint.waypoint_id)}
                  onBlur={() => setHoveredWaypointId((current) => current === waypoint.waypoint_id ? null : current)}
                  onClick={() => missions[0] && void openMission(missions[0])}
                  title={missions[0] ? t('openLatestRun') : undefined}>
                  <span className="waypoint-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="waypoint-name"><strong>{deviceLabel(waypoint.device_name, locale)}</strong><small>{zoneLabel(waypoint.zone, locale)} · {waypoint.device_id}{waypoint.position ? ` · ${t('pointPosition')} X ${waypoint.position.x}, Y ${waypoint.position.y} m` : ''}</small></span>
                  <span className={`waypoint-reading severity-${severity.toLowerCase()}`}>
                    {observation ? `${measurement(observation.pressure_mpa, 'MPa', locale, 2)}  /  ${measurement(observation.temperature_c, '°C', locale)}` : t('unknownStatus')}
                  </span>
                </button>
              })}
            </div>
          </div>

          <div className="site-panel latest-run-panel">
            <div className="site-panel-heading"><div><span className="eyebrow">{t('latestRun')}</span><h2>{missions[0]?.run_id || t('noRunYet')}</h2></div>{missions[0] && <Status value={missions[0].status} locale={locale} unknownLabel={t('unknownStatus')} />}</div>
            {missions[0] ? <>
              <div className="latest-run-meta"><span>{missions[0].execution_backend === 'slurm' ? t('slurmCluster') : t('offlineAdapter')}</span><time>{formatTime(missions[0].updated_at, locale)}</time></div>
              <div className="run-metrics">
                <div><span>{t('observedPoints')}</span><strong>{latestMissionDetail ? `${latestObservedCount} / ${site?.waypoints.length || 0}` : '—'}</strong></div>
                <div><span>{t('reportedFindings')}</span><strong className={latestFindingCount ? 'finding-count' : ''}>{latestMissionDetail ? latestFindingCount : '—'}</strong></div>
                <div><span>{t('pendingOrders')}</span><strong>{pendingOrders.filter((order) => order.run_id === missions[0].run_id).length}</strong></div>
              </div>
              <div className="latest-run-source"><span>{t('dataSource')}</span><strong>{sourceLabel(latestMissionDetail?.result?.source || latestMissionDetail?.manifest?.source, locale)}</strong></div>
              {latestMissionDetail?.result?.results.length === 0 && <div className="latest-run-empty"><Activity size={15} />{t('noReadingsYet')}</div>}
            </> : <div className="latest-run-empty"><Activity size={16} /><span>{t('noRunYet')}</span>{canOperate && <button type="button" className="secondary-button" onClick={() => setShowCreate(true)}><Plus size={14} />{t('createInspection')}</button>}</div>}
              <div className="executor-note"><span>{t('configuredRobot')}</span><strong>{robotModelLabel(dashboard?.robot.model, locale) || t('loading')}</strong><small>{dashboard?.robot.robot_id || '—'} · {t('simulationOnly')}</small></div>
          </div>
        </section>

        {section === 'simulation' && industrialSite && <section className="industrial-registry" aria-label={t('industrialRegistryTitle')}>
          <div className="section-heading industrial-registry-heading">
            <div><h2>{t('industrialRegistryTitle')}</h2><p>{t('industrialRegistryCopy')}</p></div>
            <span className={`readiness-badge${industrialSite.readiness.status === 'FIELD_READY' ? ' readiness-ready' : ''}`}><i />{industrialSite.readiness.status === 'FIELD_READY' ? t('fieldVerified') : t('fieldDataPending')}</span>
          </div>
          <div className="industrial-summary">
            <div><span>{t('readinessStatus')}</span><strong>{industrialSite.readiness.status === 'FIELD_READY' ? t('fieldVerified') : t('fieldDataPending')}</strong><small>{operatingModeLabel(industrialSite.site.industrial_profile.operating_mode, locale)}</small></div>
            <div><span>{t('assetCount')}</span><strong>{industrialSite.readiness.asset_count}</strong><small>{t('assetRegister')}</small></div>
            <div><span>{t('waypoints')}</span><strong>{industrialSite.readiness.waypoint_count}</strong><small>{t('inspectionPoints')}</small></div>
            <div><span>{t('sensorCount')}</span><strong>{industrialSite.readiness.sensor_contract_count}</strong><small>{industrialSite.site.industrial_profile.model_revision}</small></div>
          </div>
          <div className="industrial-registry-grid">
            <section className="industrial-panel asset-register-panel">
              <div className="industrial-panel-heading"><div><span className="eyebrow">{t('assetRegister')}</span><h3>{siteNameLabel(industrialSite.site.site_name, locale)}</h3></div><span>{coordinateSystemLabel(industrialSite.site.industrial_profile.coordinate_system, locale)} · {unitSystemLabel(industrialSite.site.industrial_profile.unit_system, locale)}</span></div>
              <div className="table-wrap industrial-table-wrap"><table className="industrial-table"><thead><tr><th>ID</th><th>{t('assetRegister')}</th><th>{t('zoneName')}</th><th>{t('modelSource')}</th><th>{t('inspectionPoints')}</th></tr></thead><tbody>
                {industrialSite.site.assets.map((asset) => {
                  const zone = industrialSite.site.zones.find((item) => item.zone_id === asset.zone_id)
                  return <tr key={asset.asset_id}><td><strong>{asset.asset_id}</strong><small>{assetTypeLabel(asset.asset_type, locale)}</small></td><td>{deviceLabel(asset.display_name, locale)}<small>{asset.model_asset}</small></td><td>{zoneLabel(zone?.name || asset.zone_id, locale)}</td><td><span className={`registry-status registry-status-${asset.model_status}`}><i />{industrialModelLabel(asset.model_status, locale)}</span></td><td className="industrial-point-count">{asset.inspection_points.length}</td></tr>
                })}
              </tbody></table></div>
            </section>
            <section className="industrial-panel safety-panel">
              <div className="industrial-panel-heading"><div><span className="eyebrow">{t('sensorContracts')}</span><h3>{t('safetyGate')}</h3></div><ShieldCheck size={17} /></div>
              <div className="sensor-contract-list">{industrialSite.site.sensor_contracts.map((sensor) => <div className="sensor-contract-row" key={sensor.sensor_id}><div><strong>{sensor.sensor_id}</strong><small>{sensorChannelLabel(sensor.channel, locale)} · {sensor.unit} · {calibrationLabel(sensor.calibration, locale)}</small></div><span className={`registry-status registry-status-${sensor.source_status}`}><i />{industrialSensorLabel(sensor.source_status, locale)}</span></div>)}</div>
              <dl className="safety-contracts"><div><dt>{t('restrictedZone')}</dt><dd>{industrialSite.site.safety.restricted_zones.map((value) => safetyCodeLabel(value, locale)).join(locale === 'zh' ? '、' : ', ') || '—'}</dd></div><div><dt>{t('stopConditions')}</dt><dd>{industrialSite.site.safety.stop_conditions.map((value) => safetyCodeLabel(value, locale)).join(locale === 'zh' ? '、' : ', ')}</dd></div><div><dt>{t('humanReview')}</dt><dd>{industrialSite.site.safety.human_review_required.map((value) => safetyCodeLabel(value, locale)).join(locale === 'zh' ? '、' : ', ')}</dd></div></dl>
              {industrialSite.site.safety.no_automatic_actuation && <div className="safety-no-actuation"><ShieldCheck size={14} />{t('noAutomaticActuation')}</div>}
            </section>
          </div>
          {industrialSite.readiness.field_deployment_blockers.length > 0 && <div className="industrial-blockers"><strong><AlertTriangle size={14} />{t('fieldBlockers')}</strong><ul>{industrialSite.readiness.field_deployment_blockers.map((blocker) => <li key={blocker}>{fieldBlockerLabel(blocker, locale)}</li>)}</ul></div>}
        </section>}

        {section === 'missions' && <>
        <section className="content-section">
          <div className="section-heading"><div><h2>{t('missionActivity')}</h2><p>{t('recentFirst')}</p></div><span className="record-count">{t('showing')} {visibleMissions.length} / {missions.length} {t('records')}</span></div>
          <div className="table-toolbar"><div className="filter-tabs" role="group" aria-label={t('filterMissions')}><button className={missionFilter === 'all' ? 'filter-tab selected' : 'filter-tab'} onClick={() => setMissionFilter('all')}>{t('all')}<span>{missionCount}</span></button><button className={missionFilter === 'active' ? 'filter-tab selected' : 'filter-tab'} onClick={() => setMissionFilter('active')}>{t('inProgress')}<span>{activeCount}</span></button><button className={missionFilter === 'attention' ? 'filter-tab selected' : 'filter-tab'} onClick={() => setMissionFilter('attention')}>{t('attention')}<span>{attentionCount}</span></button><button className={missionFilter === 'completed' ? 'filter-tab selected' : 'filter-tab'} onClick={() => setMissionFilter('completed')}>{t('ended')}<span>{(counts.SUCCEEDED || 0) + (counts.CANCELLED || 0)}</span></button></div><label className="table-search"><Search size={15} /><input ref={searchInputRef} aria-label={t('searchMission')} placeholder={t('searchPlaceholder')} value={missionQuery} onChange={(event) => setMissionQuery(event.target.value)} /></label></div>
          <div className="table-wrap"><table><thead><tr><th>{t('taskRunId')}</th><th>{t('runStatus')}</th><th>{t('executor')}</th><th>{t('slurmJob')}</th><th>{t('createdAt')}</th><th aria-label={t('actions')} /></tr></thead><tbody>
            {visibleMissions.map((mission) => <tr key={mission.run_id} onClick={() => void openMission(mission)} className="clickable-row"><td><strong>{mission.run_id}</strong><small>{mission.site_id} · {t('seedShort')} {mission.seed}</small></td><td><Status value={mission.status} locale={locale} unknownLabel={t('unknownStatus')} /></td><td><span className="execution-label"><i />{mission.execution_backend === 'slurm' ? t('slurmCluster') : t('offlineAdapter')}</span></td><td className="mono">{mission.slurm_job_id || '—'}</td><td>{formatTime(mission.created_at, locale)}</td><td><button className="icon-button row-action" title={t('viewMission')} aria-label={t('viewMission')} onClick={(event) => { event.stopPropagation(); void openMission(mission) }}><ArrowRight size={15} /></button></td></tr>)}
            {visibleMissions.length === 0 && <tr><td colSpan={6} className="empty-cell">{loading ? t('loadingMissions') : missionQuery || missionFilter !== 'all' ? t('noMatchingMissions') : t('noMissions')}</td></tr>}
          </tbody></table></div>
          {historyCursors.missions && <div className="history-pagination"><button className="secondary-button" disabled={historyLoading.missions} onClick={() => void loadMoreHistory('missions')}>{historyLoading.missions ? t('loadingEarlier') : t('loadEarlier')}</button></div>}
        </section>
        <section className="content-section lower-section"><div className="section-heading"><div><h2>{t('recentReview')}</h2><p>{t('latestAlerts')}</p></div><button className="text-button" onClick={() => setSection('work-orders')}>{t('viewAll')} <ArrowRight size={15} /></button></div>
          {pendingOrders.slice(0, 5).map((order) => <div className="alert-row" key={order.ticket_id}><span className={`severity-mark severity-${order.severity.toLowerCase()}`} /><div className="alert-info"><strong>{deviceLabel(String(order.payload.device_name || order.ticket_id), locale)}</strong><small>{order.ticket_id} · {order.run_id}</small></div><span className={`severity-text severity-${order.severity.toLowerCase()}`}>{severityLabel[locale][order.severity] || order.severity}</span><span className="alert-time">{formatTime(order.created_at, locale)}</span></div>)}
          {pendingOrders.length === 0 && <div className="empty-inline"><Check size={16} />{t('noPendingOrders')}</div>}
        </section>
        </>}
      </>}

      {section === 'diagnostics' && <section className="content-section page-section diagnostics-page">
        <div className="section-heading"><div><h2>{t('diagnosticReadings')}</h2><p>{t('diagnosticsPageCopy')}</p></div>{missions[0] && <button className="secondary-button" onClick={() => void openMission(missions[0])}><FileSearch size={15} />{t('viewMission')}</button>}</div>
        {latestMissionDetail?.result ? <>
          <div className="diagnostic-meta"><span><span className="eyebrow">{t('latestRun')}</span><strong>{latestMissionDetail.run_id}</strong></span><span><span className="eyebrow">{t('dataSource')}</span><strong>{sourceLabel(latestMissionDetail.result.source, locale)}</strong></span><span className="diagnostic-caveat">{t('diagnosticSourceNote')}</span></div>
          <div className="table-wrap diagnostic-table-wrap"><table className="diagnostic-table"><thead><tr><th>{t('waypointDevice')}</th><th>{t('pressure')}</th><th>{t('temperature')}</th><th>{t('ambientTemperature')}</th><th>{t('cabinetDoor')} / {t('leakSignal')}</th><th>{t('inspectionStatus')} / {t('dataQuality')}</th><th>{t('assessment')} / {t('findingsCount')}</th></tr></thead><tbody>
            {latestMissionDetail.result.results.length === 0 && <tr><td colSpan={7} className="empty-cell">{t('noReadingsYet')}</td></tr>}
            {latestMissionDetail.result.results.map((item) => {
              const waypoint = latestMissionDetail.manifest?.site_config?.waypoints?.find((entry) => entry.waypoint_id === item.waypoint_id)
                || site?.waypoints.find((entry) => entry.waypoint_id === item.waypoint_id)
              const anomalies = item.assessment?.anomalies || []
              const severity = item.assessment?.severity || 'UNKNOWN'
              return <tr key={item.waypoint_id}>
                <td><button type="button" className="diagnostic-asset-button" aria-label={`${t('viewMission')}: ${deviceLabel(waypoint?.device_name, locale) || item.device_id}`} onClick={() => missions[0] && void openMission(missions[0])}><strong>{deviceLabel(waypoint?.device_name, locale) || item.device_id}</strong><small>{item.device_id} · {zoneLabel(waypoint?.zone || item.waypoint_id, locale)}</small></button></td>
                <td>{measurement(item.observation?.pressure_mpa, 'MPa', locale, 2)}</td>
                <td>{measurement(item.observation?.temperature_c, '°C', locale)}</td>
                <td>{measurement(item.observation?.ambient_temperature_c, '°C', locale)}</td>
                <td><strong>{item.observation?.cabinet_door_closed == null ? t('unknownStatus') : item.observation.cabinet_door_closed ? t('closed') : t('open')}</strong><small>{t('leakSignal')}: {item.observation?.leak_detected == null ? t('unknownStatus') : item.observation.leak_detected ? t('suspected') : t('notDetected')}</small></td>
                <td><strong>{statusLabel[locale][item.inspection_status] || item.inspection_status}</strong><small>{item.assessment ? qualityLabel(item.assessment.data_quality, locale) : t('unknownStatus')}</small></td>
                <td><span className={`severity-pill severity-pill-${severity.toLowerCase()}`}>{severityLabel[locale][severity] || t('unknownStatus')} · {anomalies.length}</span><small>{anomalies.length ? anomalies.map((anomaly) => anomalyTitle(anomaly.code, locale, anomaly.message)).join(' · ') : t('noAnomalies')}</small></td>
              </tr>
            })}
          </tbody></table></div>
        </> : <div className="empty-state"><Activity size={22} /><strong>{missions.length ? t('diagnosticMissingRun') : t('diagnosticNotRun')}</strong><span>{t('diagnosticsPageCopy')}</span></div>}
      </section>}

      {section === 'work-orders' && <section className="content-section page-section">
        <div className="section-heading"><div><h2>{t('reviewQueue')}</h2><p>{t('reviewSafety')}</p></div><div className="work-order-heading-meta"><span className={`integration-state${dashboard?.eam_enabled ? ' integration-state-ready' : ''}`}><i />{dashboard?.eam_enabled ? t('eamEnabled') : t('eamDisconnected')}</span><span className="record-count">{dashboard?.pending_work_orders ?? pendingOrders.length} {t('pendingCount')}</span></div></div>
        {workOrders.map((order) => <article className="work-order-row" key={order.ticket_id}>
          <div className={`work-order-severity severity-${order.severity.toLowerCase()}`}><AlertTriangle size={17} /></div>
          <div className="work-order-main"><div className="work-order-title"><h3>{deviceLabel(String(order.payload.device_name || order.ticket_id), locale)}</h3><span className={`severity-pill severity-pill-${order.severity.toLowerCase()}`}>{severityLabel[locale][order.severity] || order.severity}</span><span className="review-state">{order.review_status === 'PENDING' ? t('pending') : order.review_status === 'REVIEWED' ? t('acknowledged') : t('dismissed')}</span></div>
            <p>{(() => {
              const codes = Array.isArray(order.payload.anomaly_codes) ? order.payload.anomaly_codes as string[] : []
              if (locale === 'en' && codes.length) return codes.map((code) => {
                if (code.startsWith('TEMPERATURE_')) return t('recommendationTemperature')
                if (code === 'CABINET_DOOR_OPEN') return t('recommendationDoor')
                if (code === 'PRESSURE_CRITICAL' || code === 'PRESSURE_HIGH') return t('recommendationPressure')
                if (code === 'MEASUREMENT_MISSING') return t('recommendationMissing')
                if (code === 'LEAK_SUSPECTED') return t('recommendationLeak')
                return code
              }).filter((value, index, values) => values.indexOf(value) === index).join(' ')
              const recommendations = order.payload.recommended_actions
              return Array.isArray(recommendations) ? recommendations.map((item) => typeof item === 'string' ? localizedRecommendation(item, locale, t) : String(item)).join(' ') : localizedRecommendation(String(order.payload.recommended_action || order.payload.message || t('inspectEvidence')), locale, t)
            })()}</p>
            <div className="order-meta"><span>{order.ticket_id}</span><span>{order.run_id}</span><span>{formatTime(order.created_at, locale)}</span></div>
            {order.review_status !== 'PENDING' && <div className="review-result">{order.review_decision === 'ACKNOWLEDGED' ? t('acknowledged') : order.review_decision === 'DISMISSED' ? t('dismissed') : order.review_decision} · {order.review_comment} <span>{t('reviewedBy')} {order.reviewed_by}</span></div>}
            {order.review_decision === 'ACKNOWLEDGED' && <div className={`eam-status eam-status-${order.eam_submission?.status?.toLowerCase() || 'none'}`}>
              <span>{order.eam_submission?.status === 'SUBMITTED' ? t('eamSubmitted') : order.eam_submission?.status === 'FAILED' ? t('eamFailed') : order.eam_submission?.status === 'PENDING' ? t('eamPending') : t('eamNotSubmitted')}</span>
              {order.eam_submission?.external_id && <small>{t('eamExternalId')}: {order.eam_submission.external_id}</small>}
            </div>}
          </div>
          {canReview && order.review_status === 'PENDING' && <div className="review-actions"><input aria-label={`${order.ticket_id} ${t('reviewComment')}`} placeholder={t('reviewComment')} value={reviewDraft[order.ticket_id] || ''} onChange={(event) => setReviewDraft((current) => ({ ...current, [order.ticket_id]: event.target.value }))} /><div><button className="secondary-button" onClick={() => void reviewOrder(order, 'DISMISSED')}>{t('reject')}</button><button className="primary-button" onClick={() => void reviewOrder(order, 'ACKNOWLEDGED')}><Check size={15} />{t('confirm')}</button></div></div>}
          {canSubmitEam && dashboard?.eam_enabled && order.review_status === 'REVIEWED' && order.review_decision === 'ACKNOWLEDGED' && order.eam_submission?.status !== 'SUBMITTED' && <div className="eam-actions"><button className="secondary-button" disabled={submittingEam[order.ticket_id] || order.eam_submission?.status === 'PENDING'} onClick={() => void submitEam(order)}>{submittingEam[order.ticket_id] || order.eam_submission?.status === 'PENDING' ? t('eamSubmitting') : order.eam_submission?.status === 'FAILED' ? t('eamRetry') : t('eamSubmit')}<ArrowRight size={14} /></button></div>}
        </article>)}
        {workOrders.length === 0 && <div className="empty-state"><ClipboardCheck size={22} /><strong>{t('noOrders')}</strong><span>{t('orderSource')}</span></div>}
        {historyCursors.workOrders && <div className="history-pagination"><button className="secondary-button" disabled={historyLoading.workOrders} onClick={() => void loadMoreHistory('workOrders')}>{historyLoading.workOrders ? t('loadingEarlier') : t('loadEarlier')}</button></div>}
      </section>}

      {section === 'audit' && canReview && <section className="content-section page-section">
        <div className="section-heading"><div><h2>{t('auditTrail')}</h2><p>{t('auditDescription')}</p></div><button className="secondary-button" onClick={() => void refresh()}><RefreshCw size={15} />{t('refresh')}</button></div>
        <div className="audit-list">{auditEvents.map((event) => <div className="audit-row" key={event.event_id}><span className="audit-icon"><ShieldCheck size={16} /></span><div><strong>{auditEventLabel(event.event_type, locale)}</strong><code className="audit-event-code">{event.event_type}</code><p>{resourceTypeLabel(event.resource_type, locale)} · {event.resource_id}</p><small>{event.actor} ({roleLabel(event.actor_role, locale)})</small></div><time>{formatTime(event.created_at, locale)}</time></div>)}
          {auditEvents.length === 0 && <div className="empty-state"><FileSearch size={22} /><strong>{t('noAudit')}</strong><span>{t('auditPermission')}</span></div>}</div>
        {historyCursors.auditEvents && <div className="history-pagination"><button className="secondary-button" disabled={historyLoading.auditEvents} onClick={() => void loadMoreHistory('auditEvents')}>{historyLoading.auditEvents ? t('loadingEarlier') : t('loadEarlier')}</button></div>}
      </section>}

      <footer className="page-footer"><span><span className="service-dot" />{localDemoMode ? t('localPersistence') : t('persistence')}</span><span>{t('provenance')}</span></footer>
    </main>

    {showCreate && canOperate && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowCreate(false) }}><form className="modal" role="dialog" aria-modal="true" aria-labelledby="create-mission-title" onSubmit={createMission}>
      <div className="modal-header"><div><span className="eyebrow">{t('newRun')}</span><h2 id="create-mission-title">{t('createMissionTitle')}</h2></div><button type="button" className="icon-button" title={t('close')} aria-label={t('close')} onClick={() => setShowCreate(false)}><X size={18} /></button></div>
      <div className="modal-context"><span>{t('site')}</span><strong>{siteNameLabel(site?.site_name, locale) || t('loading')}</strong><small>{site?.site_id}</small></div>
      <fieldset className="waypoint-fieldset"><legend>{t('waypoints')} <span>{selectedWaypoints.length}/{site?.waypoints.length || 0}</span></legend>{site?.waypoints.map((waypoint) => <label className="waypoint-option" key={waypoint.waypoint_id}><input type="checkbox" checked={selectedWaypoints.includes(waypoint.waypoint_id)} onChange={(event) => setSelectedWaypoints((current) => event.target.checked ? [...current, waypoint.waypoint_id] : current.filter((id) => id !== waypoint.waypoint_id))} /><span className="checkbox-mark"><Check size={12} /></span><span><strong>{deviceLabel(waypoint.device_name, locale)}</strong><small>{waypoint.device_id} · {zoneLabel(waypoint.zone, locale)}</small></span></label>)}</fieldset>
      <label className="seed-label">{t('seed')}<input type="number" min="0" max="2147483647" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      <label className="waypoint-option virtual-render-option"><input type="checkbox" role="switch" aria-label={t('virtualWorldRender')} checked={renderVirtualWorld} onChange={(event) => setRenderVirtualWorld(event.target.checked)} /><span className="checkbox-mark"><Check size={12} /></span><span><strong>{t('virtualWorldRender')}</strong><small>{t('virtualWorldRenderHint')}</small></span></label>
      <div className="source-note"><Clock3 size={15} /><span>{t('simulationDisclaimer')} <code>synthetic_simulation</code>; {t('syntheticOnly')}</span></div>
      <div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setShowCreate(false)}>{t('cancel')}</button><button type="submit" className="primary-button" disabled={submitting || selectedWaypoints.length === 0}>{submitting ? t('submitting') : <><ArrowDownToLine size={16} />{dashboard?.execution_backend === 'slurm' ? t('submitSlurm') : t('createOfflineMission')}</>}</button></div>
    </form></div>}

    {selectedMission && <div className="modal-backdrop detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeMissionDetails() }}><section className="detail-panel" role="dialog" aria-modal="true" aria-labelledby="mission-detail-title"><div className="modal-header"><div><span className="eyebrow">{t('missionDetail')}</span><h2 id="mission-detail-title">{selectedMission.run_id}</h2></div><button className="icon-button" title={t('close')} aria-label={t('close')} onClick={closeMissionDetails}><X size={18} /></button></div>
      <div className="detail-status"><Status value={selectedMission.status} locale={locale} unknownLabel={t('unknownStatus')} /><span>{selectedMission.execution_backend === 'slurm' ? `${t('slurmJobLabel')} ${selectedMission.slurm_job_id || t('waitingSubmit')}` : t('offlineAdapter')}</span></div>
      <section className="trace-section" aria-label={t('executionTrace')}>
        <h3>{t('executionTrace')}</h3>
        <ol className="execution-trace">
          <li className="trace-complete"><span className="trace-marker"><Check size={11} /></span><span>{t('phaseCreated')}</span><small>{formatTime(selectedMission.created_at, locale)}</small></li>
          <li className={`trace-${executionState}`}><span className="trace-marker" /><span>{t('phaseExecution')}</span><small>{traceStateLabel[executionState]}</small></li>
          <li className={`trace-${resultState}`}><span className="trace-marker" /><span>{t('phaseResults')}</span><small>{traceStateLabel[resultState]}</small></li>
          <li className={`trace-${reviewState}`}><span className="trace-marker" /><span>{t('phaseReview')}</span><small>{selectedOrders.some((order) => order.review_status === 'PENDING') ? t('reviewPending') : missionDetail?.result ? selectedOrders.length ? t('reviewComplete') : t('reviewNotRequired') : traceStateLabel[reviewState]}</small></li>
        </ol>
      </section>
      {selectedMission.error && <div className="notice error-notice">{selectedMission.error}</div>}
      {!missionDetail && <div className="empty-inline">{t('loadingMissionDetail')}</div>}
      {missionDetail && <>
        <dl className="mission-metadata">
          <div><dt>{t('dataSource')}</dt><dd>{sourceLabel(missionDetail.result?.source || missionDetail.manifest?.source, locale)}</dd></div>
          {missionDetail.manifest?.demo_scenario && <div><dt>{t('demoScenario')}</dt><dd>{missionDetail.manifest.demo_scenario === 'synthetic_anomaly' ? t('syntheticAnomalyScenario') : missionDetail.manifest.demo_scenario === 'successful' ? t('successfulScenario') : missionDetail.manifest.demo_scenario}</dd></div>}
          <div><dt>{t('seed')}</dt><dd>{selectedMission.seed}</dd></div>
          {missionDetail.manifest?.virtual_world?.render_backend && <div><dt>{t('virtualWorldRender')}</dt><dd>{missionDetail.manifest.virtual_world.render_backend.toUpperCase()}</dd></div>}
          {missionDetail.manifest?.software_version && <div><dt>{t('softwareVersion')}</dt><dd>{missionDetail.manifest.software_version}</dd></div>}
          {missionDetail.manifest?.config_sha256 && <div><dt>{t('configDigest')}</dt><dd title={missionDetail.manifest.config_sha256}>{missionDetail.manifest.config_sha256.slice(0, 16)}…</dd></div>}
        </dl>
        {(virtualSceneGlb || virtualSceneCameras.length > 0) && <VirtualSceneViewer glbArtifact={virtualSceneGlb} cameraArtifacts={virtualSceneCameras} token={session?.access_token || ''} locale={locale} productMode={isAuditableLocalDemo} advancedMode={isV34LocalDemo} routeWaypoints={site?.waypoints} routePolyline={sceneRoutePlan.polyline} />}
        {replayHasArtifacts && <SynchronizedInspectionReplay missionDetail={missionDetail} missionArtifacts={missionArtifacts} token={session?.access_token || ''} locale={locale} site={site} productMode={isAuditableLocalDemo} />}
        {missionDetail.result && <section className="result-evidence">
          <div className="detail-section-heading"><h3>{t('resultEvidence')}</h3><span>{missionDetail.result.results.length} {t('waypoints').toLowerCase()}</span></div>
          <div className="waypoint-results">{missionDetail.result.results.map((item) => {
              const waypoint = missionDetail.manifest?.site_config?.waypoints?.find((entry) => entry.waypoint_id === item.waypoint_id)
            const observation = item.observation
            const anomalies = item.assessment?.anomalies || []
            const confidence = observation?.sensor_confidence || {}
            const linkedOrder = item.work_order && selectedOrders.find((order) => order.ticket_id === String(item.work_order?.ticket_id))
            const readings: Array<[string, string]> = [
              [t('pressure'), measurement(observation?.pressure_mpa, 'MPa', locale, 2)],
              [t('temperature'), measurement(observation?.temperature_c, '°C', locale)],
              [t('ambientTemperature'), measurement(observation?.ambient_temperature_c, '°C', locale)],
              [t('cabinetDoor'), observation?.cabinet_door_closed == null ? t('unknownStatus') : observation.cabinet_door_closed ? t('closed') : t('open')],
              [t('leakSignal'), observation?.leak_detected == null ? t('unknownStatus') : observation.leak_detected ? t('suspected') : t('notDetected')],
            ]
            return <article className="waypoint-result" key={item.waypoint_id}>
              <header className="waypoint-result-header"><div><h4>{deviceLabel(waypoint?.device_name, locale) || item.device_id}</h4><span>{item.device_id} · {zoneLabel(waypoint?.zone || item.waypoint_id, locale)}</span></div><span className={`severity-pill severity-pill-${(item.assessment?.severity || 'UNKNOWN').toLowerCase()}`}>{severityLabel[locale][item.assessment?.severity || 'UNKNOWN'] || t('unknownStatus')}</span></header>
              <div className="waypoint-state-row"><span>{t('navigationStatus')}: {statusLabel[locale][item.navigation_status] || item.navigation_status}</span><span>{t('inspectionStatus')}: {statusLabel[locale][item.inspection_status] || item.inspection_status}</span>{item.assessment && <span>{t('dataQuality')}: {qualityLabel(item.assessment.data_quality, locale)}</span>}</div>
              {observation ? <>
                <dl className="measurement-grid">{readings.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
                <div className="observation-source"><span>{sourceLabel(observation.source, locale)}</span><time>{formatTime(observation.timestamp_utc, locale)}</time><code>{observation.sample_id}</code></div>
                {Object.keys(confidence).length > 0 && <div className="confidence-row"><span>{t('confidence')}</span>{Object.entries(confidence).map(([name, value]) => <span key={name}>{name} {Math.round(value * 100)}%</span>)}</div>}
                {observation.domain?.rendered_image_available === false && <p className="evidence-note">{t('visualEvidence')}: {t('visualUnavailable')}</p>}
              </> : <div className="empty-inline">{t('observationMissing')}</div>}
              <div className="anomaly-section"><strong>{t('anomalyEvidence')}</strong>
                {anomalies.length ? anomalies.map((anomaly) => <div className={`anomaly-evidence severity-${anomaly.severity.toLowerCase()}`} key={anomaly.code}><div><b>{anomalyTitle(anomaly.code, locale, anomaly.message)}</b><code>{anomaly.code}</code></div><p>{anomalyDescription(anomaly, locale)}</p></div>) : <span className="no-anomalies">{t('noAnomalies')}</span>}
              </div>
              {linkedOrder && <div className="linked-work-order"><ClipboardCheck size={14} /><span>{linkedOrder.ticket_id}</span><strong>{linkedOrder.review_status === 'PENDING' ? t('reviewPending') : linkedOrder.review_decision === 'ACKNOWLEDGED' ? t('acknowledged') : t('dismissed')}</strong></div>}
              {item.error && <div className="notice error-notice">{item.error}</div>}
            </article>
          })}</div>
        </section>}
        <section className="artifact-section">
          <div className="detail-section-heading"><h3>{t('generatedArtifacts')}</h3><span>{missionArtifacts.length}</span></div>
          {artifactError && <div className="notice error-notice artifact-notice">{artifactError}</div>}
          {artifactLoading && <div className="empty-inline">{t('artifactsLoading')}</div>}
          {!artifactLoading && missionArtifacts.length === 0 && <div className="empty-inline">{t('noArtifacts')}</div>}
          {missionArtifacts.map((artifact) => <button className="artifact-download" type="button" key={artifact.artifact_id} onClick={() => void downloadArtifact(artifact)} disabled={downloadingArtifact === artifact.artifact_id} title={artifact.sha256}>
            <span><strong>{artifactLabel(artifact.name, locale)}</strong><small>{artifact.name} · {formatBytes(artifact.size_bytes, locale)} · {sourceLabel(artifact.source, locale)} · SHA-256 {artifact.sha256.slice(0, 12)}…</small></span>
            <span>{downloadingArtifact === artifact.artifact_id ? t('submitting') : <>{t('download')} <ArrowDownToLine size={14} /></>}</span>
          </button>)}
        </section>
      </>}
      {canOperate && ['QUEUED', 'SUBMITTING', 'SUBMITTED', 'PENDING', 'RUNNING'].includes(selectedMission.status) && <button className="danger-button" onClick={() => void cancelMission(selectedMission)}><X size={15} />{t('cancelMission')}</button>}
    </section></div>}
  </div>
}

export default App
