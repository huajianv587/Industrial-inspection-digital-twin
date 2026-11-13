import { execFile } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { promisify } from 'node:util'
import { chromium } from '../web/node_modules/playwright/index.mjs'

const run = promisify(execFile)
const ROOT = path.resolve(decodeURIComponent(new URL('..', import.meta.url).pathname))
const OUTPUT_ROOT = path.join(ROOT, 'outputs', 'demo-video-20261030')

const chapters = [
  { id: '01-title-and-positioning', start: 0, end: 25, title: { zh: '标题与系统定位', en: 'Title and system positioning' } },
  { id: '02-portal-overview', start: 25, end: 70, title: { zh: '门户首页与项目概览', en: 'Portal and project overview' } },
  { id: '03-operations-console', start: 70, end: 115, title: { zh: '运营控制台', en: 'Operations console' } },
  { id: '04-digital-twin-multiview', start: 115, end: 180, title: { zh: '3D 数字孪生与多机位', en: '3D digital twin and multi-camera views' } },
  { id: '05-top-down-route-planning', start: 180, end: 245, title: { zh: '工厂俯视平面与避障路线', en: 'Top-down plant plan and collision-safe route' } },
  { id: '06-synchronized-video-replay', start: 245, end: 310, title: { zh: '机器人视角与 CCTV 同步回放', en: 'Robot view and CCTV synchronized replay' } },
  { id: '07-evidence-workbench', start: 310, end: 365, title: { zh: '证据工作台与逐帧分析', en: 'Evidence workbench and frame analysis' } },
  { id: '08-anomaly-review-and-eam', start: 365, end: 435, title: { zh: '合成异常、人工复核与 EAM', en: 'Synthetic anomaly, review, and EAM' } },
  { id: '09-summary-and-boundary', start: 435, end: 465, title: { zh: '产品总结与仿真边界', en: 'Product summary and simulation boundary' } },
]

const cueSets = {
  zh: [
    [0, 7, '工业巡检平台'],
    [7, 16, '单站点工业运维系统：从空间仿真、路线规划到证据闭环。'],
    [16, 25, '本演示使用本地 Blender / Three.js 合成仿真数据，不代表真实机器狗或现场视频。'],
    [25, 38, '门户首页先说明系统使命、当前状态与交付边界。'],
    [38, 52, '右侧工程平面图展示厂区坐标、设备点位和避障服务通道。'],
    [52, 70, '所有点位都带有设备编号、平面坐标和可追溯的仿真状态。'],
    [70, 85, '进入运营控制台，首先查看站点、执行模式和现场机柜状态。'],
    [85, 100, 'KPI、任务记录、Worker 心跳和数据库状态集中在同一工作面。'],
    [100, 115, '系统支持中文和英文整站切换，数据字段保持一致。'],
    [115, 132, '打开 V36 成功任务，进入 3D 数字孪生工作台。'],
    [132, 151, '场景支持总览、操作员、机器人、环绕和设备细节等多机位。'],
    [151, 180, '屋顶切换、OSD 时间码、渲染后端和帧率共同说明当前画面来源。'],
    [180, 198, '俯视平面使用本地 XY 坐标，把设备区、服务通道、管线和航点放在同一张图上。'],
    [198, 220, '路线沿真实通道转弯，并显示安全缓冲、路线段数和总长度。'],
    [220, 245, '机器人位置、当前航点和坐标随路线帧推进，不再是两点直线连线。'],
    [245, 262, '同步回放把机器人头顶 RGB、仓库 CCTV 和路线位置绑定到同一条时间轴。'],
    [262, 286, '这里把速度降到 0.25 倍，暂停和逐帧推进用于核对画面是否与路线一致。'],
    [286, 310, '同一路线帧、时间码和当前设备让多机位证据可以互相验证。'],
    [310, 328, '证据工作台支持航点、机位和证据状态筛选。'],
    [328, 348, '每一帧都保留来源、渲染帧、分辨率和双路图像哈希。'],
    [348, 365, '原始合成图片可独立打开，便于人工逐帧复核。'],
    [365, 382, '下面演示隔离的本地合成异常任务，不改变 V36 成功任务。'],
    [382, 402, '操作员填写复核意见并确认，系统记录复核人、时间和决策。'],
    [402, 420, '管理员随后可以把已确认工单提交到模拟 EAM 适配器。'],
    [420, 435, '审计日志保留结果导入、人工复核和 EAM 提交事件。'],
    [435, 450, '这套系统把空间、路线、双路视频、证据和工单闭环放进一个可演示工作台。'],
    [450, 465, '当前边界是本地 Blender / Three.js 合成仿真；未来可接入真实机器人、摄像头和 EAM。'],
  ],
  en: [
    [0, 7, 'Industrial Inspection Platform'],
    [7, 16, 'A single-site operations system covering simulation, route planning, and an auditable evidence loop.'],
    [16, 25, 'This demo uses local Blender / Three.js synthetic data. It is not a physical robot or field video.'],
    [25, 38, 'The portal establishes the mission, current state, and delivery boundary first.'],
    [38, 52, 'The engineering plan exposes plant coordinates, equipment points, and collision-safe service lanes.'],
    [52, 70, 'Every point carries a device identifier, plan coordinate, and traceable synthetic status.'],
    [70, 85, 'The operations console starts with site identity, execution mode, and field cabinet status.'],
    [85, 100, 'KPIs, mission records, worker heartbeat, and database status share one operational surface.'],
    [100, 115, 'The full site switches between Chinese and English while keeping the data model unchanged.'],
    [115, 132, 'Open the V36 successful mission to enter the 3D digital-twin workbench.'],
    [132, 151, 'The scene provides overview, operator, robot, orbit, and equipment-detail camera views.'],
    [151, 180, 'Roof cutaway, OSD timecode, render backend, and frame rate make the image provenance explicit.'],
    [180, 198, 'The top-down plan shares one local XY projection for equipment, lanes, piping, and waypoints.'],
    [198, 220, 'The route follows real aisle turns and exposes clearance, segment count, and total distance.'],
    [220, 245, 'Robot pose, current waypoint, and coordinates advance with the route frame instead of a straight line.'],
    [245, 262, 'Robot-head RGB, warehouse CCTV, and route position share one synchronized replay timeline.'],
    [262, 286, 'Playback is slowed to 0.25x so pause and frame stepping can verify route-to-image alignment.'],
    [286, 310, 'Shared route frames, timecode, and current asset make the paired views independently checkable.'],
    [310, 328, 'The evidence workbench filters by waypoint, camera, and evidence state.'],
    [328, 348, 'Each frame retains provenance, render frame, resolution, and paired image hashes.'],
    [348, 365, 'The original synthetic image can be opened for frame-level human review.'],
    [365, 382, 'Next is an isolated local synthetic anomaly task; the successful V36 mission is untouched.'],
    [382, 402, 'An operator records a review comment and acknowledges the finding with a named decision.'],
    [402, 420, 'An administrator can then submit the acknowledged work order to the simulated EAM adapter.'],
    [420, 435, 'The audit trail retains result import, human review, and EAM submission events.'],
    [435, 450, 'This brings space, route, paired video, evidence, and work-order closeout into one product surface.'],
    [450, 465, 'The current boundary is local Blender / Three.js synthetic simulation. Real robots, cameras, and EAM can be integrated later.'],
  ],
}

function timestamp(seconds) {
  const safe = Math.max(0, Number(seconds))
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const whole = Math.floor(safe % 60)
  const millis = Math.round((safe - Math.floor(safe)) * 1000)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(whole).padStart(2, '0')},${String(millis).padStart(3, '0')}`
}

function escapeSubtitle(text) {
  return text.replaceAll('\n', '\\N')
}

function makeSrt(locale) {
  return cueSets[locale].map(([start, end, text], index) => `${index + 1}\n${timestamp(start)} --> ${timestamp(end)}\n${escapeSubtitle(text)}\n`).join('\n')
}

function makeVtt(locale) {
  return `WEBVTT\n\n${cueSets[locale].map(([start, end, text], index) => `${index + 1}\n${timestamp(start).replace(',', '.')} --> ${timestamp(end).replace(',', '.')}\n${escapeSubtitle(text)}\n`).join('\n')}`
}

function makeVoiceover(locale) {
  const header = locale === 'zh'
    ? '# 工业巡检系统演示配音稿（中文）\n\n版本：2026-10-30\n\n说明：以下文本与烧录字幕按时间码对应；不含背景音乐和 AI 配音。\n\n'
    : '# Industrial Inspection System Demo Voiceover (English)\n\nVersion: 2026-10-30\n\nNote: The following script is aligned to the burned-in subtitles. No background music or generated voice is included.\n\n'
  return header + chapters.map((chapter, chapterIndex) => {
    const rows = cueSets[locale].filter(([start]) => start >= chapter.start && start < chapter.end)
    const lines = rows.map(([start, end, text]) => `- ${timestamp(start)}–${timestamp(end)} ${text}`).join('\n')
    return `## ${String(chapterIndex + 1).padStart(2, '0')} · ${chapter.title[locale]}\n\n${lines}\n`
  }).join('\n')
}

async function ffmpeg(args) {
  await run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { maxBuffer: 1024 * 1024 * 16 })
}

async function ffprobeDuration(filePath) {
  const { stdout } = await run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', filePath])
  return Number(stdout.trim())
}

function subtitleOverlayHtml(text) {
  const escaped = text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 1440px; height: 900px; background: transparent; overflow: hidden; }
    .caption { position: absolute; left: 90px; right: 90px; bottom: 28px; display: flex; justify-content: center; }
    .caption span { max-width: 1260px; padding: 12px 22px 13px; border-left: 3px solid #0066ff; background: rgba(7, 13, 21, 0.86); color: #f8fafd; font: 600 24px/1.42 "PingFang SC", "SF Pro Display", Arial, sans-serif; letter-spacing: 0; text-align: center; text-shadow: 0 1px 2px rgba(0,0,0,.7); }
  </style></head><body><div class="caption"><span>${escaped}</span></div></body></html>`
}

async function renderOverlayPngs(browser, locale, chapterIndex, rows, chapterRoot) {
  const overlayRoot = path.join(OUTPUT_ROOT, '.subtitle-overlays', locale, String(chapterIndex + 1).padStart(2, '0'))
  await mkdir(overlayRoot, { recursive: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
  const results = []
  for (const [cueIndex, [start, end, text]] of rows.entries()) {
    const filePath = path.join(overlayRoot, `${String(cueIndex + 1).padStart(2, '0')}.png`)
    await page.setContent(subtitleOverlayHtml(text), { waitUntil: 'load' })
    await page.screenshot({ path: filePath, omitBackground: true })
    results.push({ start, end, filePath })
  }
  await page.close()
  return results
}

async function buildLocale(locale, manifest, browser) {
  const chapterRoot = path.join(OUTPUT_ROOT, `chapters-${locale}`)
  await mkdir(chapterRoot, { recursive: true })
  const localFiles = []
  for (const [index, chapter] of chapters.entries()) {
    const record = manifest.recordings.find((item) => item.locale === locale && item.chapter === index + 1)
    if (!record) throw new Error(`Missing recording for ${locale} chapter ${index + 1}`)
    const localCueRows = cueSets[locale]
      .filter(([start, end]) => end > chapter.start && start < chapter.end)
      .map(([start, end, text]) => [Math.max(0, start - chapter.start), Math.min(chapter.end - chapter.start, end - chapter.start), text])
    const localSrt = localCueRows.map(([start, end, text], cueIndex) => `${cueIndex + 1}\n${timestamp(start)} --> ${timestamp(end)}\n${escapeSubtitle(text)}\n`).join('\n')
    const localSrtPath = path.join(chapterRoot, `.${String(index + 1).padStart(2, '0')}.srt`)
    await writeFile(localSrtPath, localSrt, 'utf8')
    const outputPath = path.join(chapterRoot, `chapter-${String(index + 1).padStart(2, '0')}-${chapter.id}.mp4`)
    const overlays = await renderOverlayPngs(browser, locale, index, localCueRows, chapterRoot)
    const inputArgs = ['-i', record.raw_path]
    overlays.forEach(({ filePath }) => inputArgs.push('-framerate', '30', '-loop', '1', '-i', filePath))
    const filterParts = []
    let previous = '0:v'
    overlays.forEach(({ start, end }, overlayIndex) => {
      const overlayLabel = `ov${overlayIndex}`
      const outputLabel = `v${overlayIndex}`
      filterParts.push(`[${overlayIndex + 1}:v]format=rgba[${overlayLabel}]`)
      filterParts.push(`[${previous}][${overlayLabel}]overlay=0:0:eof_action=pass:enable='between(t,${start},${end})'[${outputLabel}]`)
      previous = outputLabel
    })
    await ffmpeg([
      ...inputArgs,
      '-filter_complex', filterParts.join(';'), '-map', `[${previous}]`, '-t', String(chapter.end - chapter.start),
      '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart', outputPath,
    ])
    localFiles.push(outputPath)
  }
  const concatPath = path.join(OUTPUT_ROOT, `concat-${locale}.txt`)
  await writeFile(concatPath, localFiles.map((file) => `file '${file.replaceAll("'", "'\\''")}'`).join('\n') + '\n', 'utf8')
  const finalPath = path.join(OUTPUT_ROOT, `inspection-demo-${locale}.mp4`)
  await ffmpeg(['-f', 'concat', '-safe', '0', '-i', concatPath, '-c', 'copy', '-movflags', '+faststart', finalPath])
  return { finalPath, localFiles, durationSeconds: await ffprobeDuration(finalPath) }
}

const manifestPath = path.join(OUTPUT_ROOT, 'recording-manifest.json')
const manifest = JSON.parse(await readFile(manifestPath, 'utf8'))
await mkdir(OUTPUT_ROOT, { recursive: true })

for (const locale of ['zh', 'en']) {
  await writeFile(path.join(OUTPUT_ROOT, `inspection-demo-${locale}.srt`), makeSrt(locale), 'utf8')
  await writeFile(path.join(OUTPUT_ROOT, `inspection-demo-${locale}.vtt`), makeVtt(locale), 'utf8')
  await writeFile(path.join(OUTPUT_ROOT, `voiceover-script-${locale}.md`), makeVoiceover(locale), 'utf8')
}

const deliverables = {}
const subtitleBrowser = await chromium.launch({ channel: 'chrome', headless: true })
try {
  for (const locale of ['zh', 'en']) deliverables[locale] = await buildLocale(locale, manifest, subtitleBrowser)
} finally {
  await subtitleBrowser.close()
}

const editDecisionList = `# Demo video edit decision list

Date: 2026-10-30

The two language versions use the same nine-chapter shot plan and a 1440×900 Chrome viewport. Each chapter is recorded as an independent Chrome WebM source, then encoded to H.264 MP4 with burned-in subtitles. There is no background music and no generated voice track.

| Chapter | Timecode | Visual action | Evidence shown |
| --- | --- | --- | --- |
${chapters.map((chapter, index) => `| ${String(index + 1).padStart(2, '0')} | ${timestamp(chapter.start)}–${timestamp(chapter.end)} | ${chapter.title.en} | Chrome-operated local demo UI |`).join('\n')}

The anomaly workflow is isolated at the browser route layer and is explicitly synthetic. It does not write a work order into the local V36 database, call a real EAM endpoint, or create a physical action.
`
await writeFile(path.join(OUTPUT_ROOT, 'edit-decision-list.md'), editDecisionList, 'utf8')

manifest.video_outputs = deliverables
manifest.subtitle_outputs = {
  zh: {
    srt: path.join(OUTPUT_ROOT, 'inspection-demo-zh.srt'),
    vtt: path.join(OUTPUT_ROOT, 'inspection-demo-zh.vtt'),
    voiceover: path.join(OUTPUT_ROOT, 'voiceover-script-zh.md'),
  },
  en: {
    srt: path.join(OUTPUT_ROOT, 'inspection-demo-en.srt'),
    vtt: path.join(OUTPUT_ROOT, 'inspection-demo-en.vtt'),
    voiceover: path.join(OUTPUT_ROOT, 'voiceover-script-en.md'),
  },
}
manifest.edit_decision_list = path.join(OUTPUT_ROOT, 'edit-decision-list.md')
manifest.built_at = new Date().toISOString()
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')

console.log(JSON.stringify({ deliverables, manifestPath }, null, 2))
