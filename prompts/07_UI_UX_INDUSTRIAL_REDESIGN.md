# Codex 任务书：工业巡检系统 UI/UX 全维度企业级工控重塑 (完整落地版 V3)

## 一、必须立即纠正的问题与清洗原则
1. **停止追加式补丁（CSS Patchwork）**：
   - 全面清理 `project-home.desktop.css`（从 53KB 瘦身）与 `styles.css`（从 174KB 瘦身）尾部重复追加的冲突类。
   - 彻底删除旧版的枯草绿（`#315b43`）、土黄色（`#e4b95f`）和泛灰纸底（`#f7f8f6`），杜绝样式冲突导致界面发灰发脏。
2. **彻底纠正“一刀切 11px”的呆板排版**：
   - **大盘核心 KPI 读数**：`26px ~ 32px` 粗体等宽（`JetBrains Mono`），强制开启 `font-variant-numeric: tabular-nums`；
   - **页面核心大标题**：`38px ~ 42px`，紧凑字间距（`-0.02em`），金属质感高光；
   - **正文与表格数据**：恢复为清晰舒适的 `13px ~ 14px`（行高 `1.55`，主文本深碳灰 `#0A101D`）；
   - **仅用于元数据标签与状态码**：使用 `11px`（字重 600，大写，`letter-spacing: 0.05em`）。
3. **摒弃廉价小卡片堆叠，引入“一体化机架控制台（Integrated Chassis）”**：
   - 采用纯正工控深色调：深渊碳黑（`#080C10`）与石墨暗灰（`#0E141B`）；
   - 高精工业蓝（`#0066FF`）与微波青（`#00E5FF`）作为信号高光；
   - 加入四角十字准星标（`+` Reticle Crosshairs）、刻度线（Tick Rulers）、硬件 LED 呼吸发光灯与 CAD 蓝图雷达平显。

---

## 二、全局设计代币规范 (`:root` Tokens)
请在 `web/src/styles.css` 与 `web/src/project-home.desktop.css` 的 `:root` 顶部统一定义：

```css
:root {
  /* 表面基底 */
  --ind-bg: #F0F3F7;
  --ind-surface-0: #FFFFFF;
  --ind-surface-1: #F8FAFD;
  --ind-surface-2: #EDF2F7;
  --ind-surface-dark: #080C10;
  --ind-surface-dark-panel: #0E141B;
  --ind-surface-dark-sub: #16202C;

  /* 文字颜色 */
  --ind-ink-primary: #0A101D;
  --ind-ink-secondary: #2C3E50;
  --ind-ink-muted: #5A6E85;
  --ind-ink-inverse: #F8FAFD;
  --ind-ink-mono: #1E293B;

  /* 分割线与网格 */
  --ind-line-hairline: #DCE3EC;
  --ind-line-strong: #BDC9D7;
  --ind-line-dark: #1E293B;
  --ind-grid-dark: rgba(30, 41, 59, 0.45);

  /* 工业品牌与主交互 */
  --ind-accent: #0066FF;
  --ind-accent-hover: #0052CC;
  --ind-accent-subtle: #E8F1FF;
  --ind-accent-glow: rgba(0, 102, 255, 0.28);
  --ind-cyan: #00E5FF;
  --ind-cyan-glow: rgba(0, 229, 255, 0.35);

  /* 工业安全信号色 (ISO 11064) */
  --ind-status-nominal: #10B981;
  --ind-status-nominal-bg: #ECFDF5;
  --ind-status-nominal-border: #A7F3D0;
  --ind-status-nominal-glow: rgba(16, 185, 129, 0.35);

  --ind-status-advisory: #0284C7;
  --ind-status-advisory-bg: #F0F9FF;
  --ind-status-advisory-border: #BAE6FD;

  --ind-status-warning: #F59E0B;
  --ind-status-warning-bg: #FFFBEB;
  --ind-status-warning-border: #FDE68A;
  --ind-status-warning-glow: rgba(245, 158, 11, 0.35);

  --ind-status-critical: #EF4444;
  --ind-status-critical-bg: #FEF2F2;
  --ind-status-critical-border: #FECACA;
  --ind-status-critical-glow: rgba(239, 68, 68, 0.4);

  --ind-status-offline: #64748B;
  --ind-status-offline-bg: #F1F5F9;

  /* 字体族 */
  --font-ui: "Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
  --font-mono: "JetBrains Mono", "Roboto Mono", "SF Mono", Menlo, Consolas, monospace;

  /* 倒角与阴影 */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --shadow-chassis: inset 0 0 30px rgba(0, 0, 0, 0.5), 0 8px 24px rgba(0, 0, 0, 0.4);
}
```

---

## 三、门户首页重塑 (`ProjectHome.tsx` + `project-home.desktop.css`)

### 1. `ProjectHome.tsx` Hero 核心结构
请将 `ProjectHome.tsx` 中的 Hero 区域彻底替换为一体化机架控制台结构：

```tsx
<section className="industrial-hero" aria-labelledby="hero-title">
  {/* 顶部遥测状态带 */}
  <div className="hero-telemetry-ribbon">
    <div className="telemetry-item">
      <span className="telemetry-led status-nominal" />
      <span className="telemetry-label">SYSTEM KERNEL:</span>
      <span className="telemetry-value">ONLINE // SIM-RUNNER</span>
    </div>
    <div className="telemetry-item">
      <span className="telemetry-label">SITE CLUSTER:</span>
      <span className="telemetry-value font-mono">{siteConfig.site_id}</span>
    </div>
    <div className="telemetry-item">
      <span className="telemetry-label">WAYPOINTS:</span>
      <span className="telemetry-value font-mono">{siteConfig.waypoints.length} PTS ACTIVE</span>
    </div>
    <div className="telemetry-item telemetry-utc">
      <span className="telemetry-label">TIME REF:</span>
      <span className="telemetry-value font-mono">UTC SYNCHRONIZED</span>
    </div>
  </div>

  {/* 主座舱视窗：55% 指令区 / 45% CAD 蓝图 HUD */}
  <div className="hero-cockpit">
    {/* 左侧：系统指令与叙事面板 */}
    <div className="hero-command-panel">
      <div className="panel-corner-cross top-left" />
      <div className="panel-corner-cross top-right" />
      <div className="panel-corner-cross bottom-left" />
      <div className="panel-corner-cross bottom-right" />

      <div className="hero-eyebrow-tag">
        <span className="tag-bracket">[</span>
        <span className="tag-text">CYBER-PHYSICAL INSPECTION OS // V1.2</span>
        <span className="tag-bracket">]</span>
      </div>

      <h1 id="hero-title" className="hero-title">
        工业四足巡检<br />
        <span className="hero-title-accent">数字孪生运维平台</span>
      </h1>

      <p className="hero-lead">
        面向复杂工业厂区构建的高确定性自主巡检系统。打通任务闭环编排、Blender/Isaac 虚拟仿真验证、规则引擎多维诊断与 EAM 运维工单。
      </p>

      {/* 核心指标微仪表带 */}
      <div className="hero-stats-strip">
        <div className="stat-unit">
          <span className="stat-num font-mono">100%</span>
          <span className="stat-desc">全流程审计可追溯</span>
        </div>
        <div className="stat-divider" />
        <div className="stat-unit">
          <span className="stat-num font-mono">&lt; 50ms</span>
          <span className="stat-desc">遥测规则评估延迟</span>
        </div>
        <div className="stat-divider" />
        <div className="stat-unit">
          <span className="stat-num font-mono">0.45m</span>
          <span className="stat-desc">碰撞安全缓冲裕度</span>
        </div>
      </div>

      <div className="hero-actions-dock">
        <a className="btn-industrial-primary" href="/console">
          <span>进入现场运营控制台</span>
          <ArrowRight size={16} />
        </a>
        <a className="btn-industrial-secondary" href="#workflow">
          <span>查看工程链路</span>
          <ArrowDown size={15} />
        </a>
      </div>

      <div className="hero-safety-notice">
        <ShieldCheck size={14} className="safety-icon" />
        <span>当前为软件基线核验状态；未提交真实集群作业，缺失测点保持 UNKNOWN，不触发自动执行动作。</span>
      </div>
    </div>

    {/* 右侧：全尺寸工业 CAD 蓝图 HUD 地图 */}
    <div className="hero-blueprint-panel">
      <div className="panel-corner-cross top-left" />
      <div className="panel-corner-cross top-right" />
      <div className="panel-corner-cross bottom-left" />
      <div className="panel-corner-cross bottom-right" />

      <div className="blueprint-header">
        <div className="blueprint-title-group">
          <span className="blueprint-badge">CAD PLAN // 2D PROJECTION</span>
          <h2 className="blueprint-heading">站点巡检拓扑与航道规划</h2>
        </div>
        <div className="blueprint-meta font-mono">
          <span>COORD: LOCAL-XY</span>
          <span className="meta-dot">·</span>
          <span>SCALE: 1:100</span>
        </div>
      </div>

      {/* CAD 蓝图 SVG 视口 */}
      <div className="blueprint-viewport">
        <svg className="blueprint-svg" viewBox="0 0 500 270" role="group">
          <rect className="blueprint-boundary" x="20" y="24" width="460" height="222" rx="2" />
          {/* 安全作业分区 */}
          <g className="blueprint-zones">
            {sitePlanZoneBoxes.map((zone) => (
              <g key={zone.id}>
                <rect x={zone.x} y={zone.y} width={zone.width} height={zone.height} />
                <text x={zone.x + 6} y={zone.y + 13}>{zone.id}</text>
              </g>
            ))}
          </g>
          {/* 指北针与标尺 */}
          <g className="blueprint-compass" transform="translate(450 46)">
            <circle cx="0" cy="0" r="12" />
            <path d="M 0 -7 L 4 5 L 0 2 L -4 5 Z" />
            <text x="0" y="-14">N</text>
          </g>
          {/* 航道导轨与发光线条 */}
          <path className="blueprint-route-glow" d={sitePlanRoutePath} />
          <path className="blueprint-route" d={sitePlanRoutePath} />
          {/* 巡检航点与雷达扫光圈 */}
          {sitePlanPoints.map(({ waypoint, index, x, y }) => (
            <g
              key={waypoint.waypoint_id}
              className={`blueprint-point ${activeWaypoint === index ? 'is-active' : ''}`}
              transform={`translate(${x} ${y})`}
              onClick={() => toggleWaypoint(index)}
            >
              <circle className="point-sonar" r="18" />
              <circle className="point-halo" r="10" />
              <circle className="point-core" r="5" />
              <text y="3">{String(index + 1).padStart(2, '0')}</text>
            </g>
          ))}
          {/* 轴线刻度 */}
          <text className="blueprint-axis" x="456" y="254">X / m</text>
          <text className="blueprint-axis" x="14" y="26">Y / m</text>
        </svg>
      </div>

      {/* 底部点位快速标签栏 */}
      <div className="blueprint-footer">
        <div className="waypoint-glance">
          {sitePlanPoints.map(({ waypoint, index }) => (
            <button
              key={waypoint.waypoint_id}
              type="button"
              className={`waypoint-glance-tag ${activeWaypoint === index ? 'is-active' : ''}`}
              onClick={() => toggleWaypoint(index)}
            >
              <i>{String(index + 1).padStart(2, '0')}</i>
              <span>{waypoint.waypoint_id.replace(/^WP_\d+_/, '')}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  </div>
</section>
```

### 2. `project-home.desktop.css` 核心样式
在桌面 CSS 中彻底应用纯净的工业座舱样式：

```css
/* 工业英雄座舱 */
.project-home .industrial-hero {
  position: relative;
  background: var(--ind-surface-dark);
  border-bottom: 1px solid var(--ind-line-dark);
  padding: 16px clamp(24px, 4vw, 64px) 48px;
  color: var(--ind-ink-inverse);
  overflow: hidden;
}

.hero-telemetry-ribbon {
  display: flex;
  align-items: center;
  gap: 28px;
  height: 38px;
  margin-bottom: 24px;
  padding: 0 16px;
  background: rgba(14, 20, 27, 0.85);
  border: 1px solid var(--ind-line-dark);
  border-radius: var(--radius-xs);
  font-size: 11px;
  letter-spacing: 0.05em;
}
.telemetry-item { display: flex; align-items: center; gap: 8px; }
.telemetry-label { color: var(--ind-ink-muted); font-weight: 500; font-family: var(--font-mono); }
.telemetry-value { color: #E2E8F0; font-weight: 600; font-family: var(--font-mono); }
.telemetry-led {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ind-status-nominal);
  box-shadow: 0 0 8px var(--ind-status-nominal-glow);
  animation: pulse-glow 2s infinite ease-in-out;
}
@keyframes pulse-glow {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}

.hero-cockpit {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 28px;
  align-items: stretch;
}

.hero-command-panel, .hero-blueprint-panel {
  position: relative;
  background: var(--ind-surface-dark-panel);
  border: 1px solid var(--ind-line-dark);
  border-radius: var(--radius-sm);
  padding: 36px 36px 32px;
  box-shadow: var(--shadow-chassis);
}

/* 十字准星标 */
.panel-corner-cross {
  position: absolute;
  width: 9px;
  height: 9px;
  pointer-events: none;
}
.panel-corner-cross::before, .panel-corner-cross::after {
  content: "";
  position: absolute;
  background: var(--ind-accent);
}
.panel-corner-cross::before { width: 9px; height: 1px; top: 4px; left: 0; }
.panel-corner-cross::after { width: 1px; height: 9px; top: 0; left: 4px; }
.panel-corner-cross.top-left { top: -5px; left: -5px; }
.panel-corner-cross.top-right { top: -5px; right: -5px; }
.panel-corner-cross.bottom-left { bottom: -5px; left: -5px; }
.panel-corner-cross.bottom-right { bottom: -5px; right: -5px; }

.hero-eyebrow-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  background: rgba(0, 102, 255, 0.1);
  border: 1px solid rgba(0, 102, 255, 0.3);
  color: #38BDF8;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  border-radius: var(--radius-xs);
  margin-bottom: 20px;
}
.hero-title {
  margin: 0 0 18px;
  font-size: 42px;
  line-height: 1.15;
  font-weight: 700;
  color: #FFFFFF;
  letter-spacing: -0.02em;
}
.hero-title-accent {
  background: linear-gradient(135deg, var(--ind-cyan) 0%, var(--ind-accent) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero-lead {
  font-size: 14px;
  line-height: 1.6;
  color: #94A3B8;
  margin-bottom: 28px;
  max-width: 560px;
}

.hero-stats-strip {
  display: flex;
  align-items: center;
  background: #090E14;
  border: 1px solid var(--ind-line-dark);
  border-radius: var(--radius-xs);
  padding: 14px 20px;
  margin-bottom: 30px;
}
.stat-unit { flex: 1; }
.stat-num {
  display: block;
  font-size: 26px;
  font-weight: 700;
  color: #F8FAFD;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
}
.stat-desc {
  display: block;
  font-size: 11px;
  color: var(--ind-ink-muted);
  margin-top: 4px;
}
.stat-divider {
  width: 1px;
  height: 32px;
  background: var(--ind-line-dark);
  margin: 0 20px;
}

.hero-actions-dock {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 22px;
}
.btn-industrial-primary {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  height: 44px;
  padding: 0 24px;
  background: var(--ind-accent);
  border: 1px solid var(--ind-accent-hover);
  border-radius: var(--radius-xs);
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 0 16px var(--ind-accent-glow);
  transition: all 0.15s ease;
}
.btn-industrial-primary:hover {
  background: var(--ind-accent-hover);
  transform: translateY(-1px);
}
.btn-industrial-secondary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 20px;
  background: transparent;
  border: 1px solid #334155;
  border-radius: var(--radius-xs);
  color: #CBD5E1;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.15s ease;
}
.btn-industrial-secondary:hover {
  border-color: #64748B;
  color: #FFFFFF;
  background: rgba(255, 255, 255, 0.04);
}
.hero-safety-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--ind-ink-muted);
}
.safety-icon { color: var(--ind-cyan); flex: none; margin-top: 1px; }

/* CAD 蓝图视口 */
.blueprint-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 14px;
}
.blueprint-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--ind-cyan);
}
.blueprint-heading {
  margin: 3px 0 0;
  font-size: 16px;
  font-weight: 600;
  color: #F8FAFD;
}
.blueprint-meta {
  font-size: 11px;
  color: var(--ind-ink-muted);
  font-family: var(--font-mono);
}
.meta-dot { margin: 0 6px; }

.blueprint-viewport {
  position: relative;
  height: 290px;
  background: #070B0E;
  border: 1px solid var(--ind-line-dark);
  border-radius: var(--radius-xs);
  background-image:
    linear-gradient(var(--ind-grid-dark) 1px, transparent 1px),
    linear-gradient(90deg, var(--ind-grid-dark) 1px, transparent 1px);
  background-size: 20px 20px;
  overflow: hidden;
}
.blueprint-svg { display: block; width: 100%; height: 100%; }
.blueprint-boundary { fill: none; stroke: rgba(56, 189, 248, 0.25); stroke-width: 1; stroke-dasharray: 4 4; }
.blueprint-zones rect { fill: rgba(14, 165, 233, 0.04); stroke: rgba(14, 165, 233, 0.2); stroke-width: 1; }
.blueprint-zones text { fill: #38BDF8; font: 9px var(--font-mono); opacity: 0.7; }
.blueprint-compass circle { fill: none; stroke: var(--ind-line-dark); }
.blueprint-compass path { fill: var(--ind-cyan); }
.blueprint-compass text { fill: var(--ind-cyan); font: 9px var(--font-mono); text-anchor: middle; font-weight: 700; }
.blueprint-route-glow { fill: none; stroke: var(--ind-accent); stroke-width: 5; opacity: 0.3; filter: blur(3px); }
.blueprint-route { fill: none; stroke: var(--ind-cyan); stroke-width: 2.2; stroke-dasharray: 6 5; }

.blueprint-point { cursor: pointer; }
.blueprint-point .point-core { fill: var(--ind-cyan); stroke: #080C10; stroke-width: 2; }
.blueprint-point .point-halo { fill: rgba(0, 229, 255, 0.2); stroke: var(--ind-cyan); stroke-width: 1; }
.blueprint-point .point-sonar {
  fill: none;
  stroke: var(--ind-cyan);
  stroke-width: 1;
  animation: sonar-ping 2.5s infinite ease-out;
}
@keyframes sonar-ping {
  0% { r: 5; opacity: 1; }
  100% { r: 24; opacity: 0; }
}
.blueprint-point text { fill: #FFFFFF; font: 10px var(--font-mono); font-weight: 700; text-anchor: middle; }
.blueprint-axis { fill: var(--ind-ink-muted); font: 10px var(--font-mono); }

.blueprint-footer { margin-top: 14px; }
.waypoint-glance { display: flex; flex-wrap: wrap; gap: 6px; }
.waypoint-glance-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #090E14;
  border: 1px solid var(--ind-line-dark);
  border-radius: var(--radius-xs);
  color: #94A3B8;
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: all 0.14s ease;
}
.waypoint-glance-tag:hover, .waypoint-glance-tag.is-active {
  border-color: var(--ind-accent);
  color: #F8FAFD;
  background: rgba(0, 102, 255, 0.15);
}
.waypoint-glance-tag i { color: var(--ind-cyan); font-style: normal; }
```

---

## 四、控制台 `App.tsx` 与 `styles.css` 彻底去 AI 模版气

### 1. 侧边栏 (`.sidebar`) 沉浸式工控底色与高质感面板
```css
.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 5;
  width: 244px;
  padding: 24px 16px 18px;
  background: var(--ind-surface-dark); /* 纯正深石墨工控黑 */
  border-right: 1px solid var(--ind-line-dark);
  color: var(--ind-ink-inverse);
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 42px;
  padding: 0 12px;
  border: 0;
  border-radius: var(--radius-xs);
  color: #94A3B8;
  background: transparent;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s ease;
}
.nav-item:hover {
  color: #FFFFFF;
  background: rgba(255, 255, 255, 0.04);
}
.nav-item.active {
  color: #FFFFFF;
  background: rgba(0, 102, 255, 0.12);
  border-left: 3px solid var(--ind-accent);
  box-shadow: inset 0 0 12px rgba(0, 102, 255, 0.1);
}
```

### 2. KPI 指标大盘 (`.summary-strip`) 层次分明
- 卡片内部指标数值强制设为 `28px`，粗体等宽：
```css
.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  background: var(--ind-surface-0);
  border: 1px solid var(--ind-line-hairline);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.summary-item {
  padding: 18px 22px;
  border-right: 1px solid var(--ind-line-hairline);
}
.summary-item:last-child { border-right: 0; }
.summary-item > span {
  display: block;
  color: var(--ind-ink-muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.summary-item > strong {
  display: block;
  margin: 8px 0 4px;
  color: var(--ind-ink-primary);
  font-size: 28px;
  font-weight: 700;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.summary-item small {
  display: block;
  color: var(--ind-ink-muted);
  font-size: 12px;
}
```

### 3. 表格数据网格 (Data Grid) 工业人机工程规范
- **表头**：大写加粗，字号固定为 `11px`，底色为 `#0B1118` 或 `#F8FAFD`；
- **表格行 (Row)**：行高统一为 `44px`，正文字号恢复为标准的 `13px`；
- **遥测数据列**：强制采用 `JetBrains Mono` 并使用 `tabular-nums` 垂直对齐：
```css
th {
  height: 42px;
  padding: 0 16px;
  color: var(--ind-ink-muted);
  background: var(--ind-surface-1);
  border-bottom: 1px solid var(--ind-line-strong);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
td {
  height: 44px;
  padding: 10px 16px;
  color: var(--ind-ink-secondary);
  border-bottom: 1px solid var(--ind-line-hairline);
  font-size: 13px;
  vertical-align: middle;
}
tr:hover td { background: rgba(0, 102, 255, 0.03); }
td strong, .mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}
```

### 4. 3D 虚拟场景视窗与视频流回放增加工业 OSD 平显
在 `App.tsx` 渲染的三维/视频监控视口最外层叠加 OSD 标尺角标与状态行：
```tsx
<div className="industrial-osd-viewport">
  <div className="osd-bracket osd-top-left">┌</div>
  <div className="osd-bracket osd-top-right">┐</div>
  <div className="osd-bracket osd-bottom-left">└</div>
  <div className="osd-bracket osd-bottom-right">┘</div>

  <div className="osd-telemetry-header">
    <span className="osd-rec-tag">● REC 30FPS</span>
    <span className="osd-meta">TC 00:08:42:15</span>
    <span className="osd-meta">LATENCY: 18ms</span>
    <span className="osd-meta">FOV: 85° // CYCLES-HW</span>
  </div>

  {/* 嵌入实际的 Three.js Canvas 或 视频 Replay */}
  {children}
</div>
```
```css
.industrial-osd-viewport {
  position: relative;
  border: 1px solid var(--ind-line-dark);
  background: #000000;
  overflow: hidden;
}
.osd-bracket {
  position: absolute;
  color: var(--ind-cyan);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1;
  pointer-events: none;
  z-index: 3;
}
.osd-top-left { top: 8px; left: 8px; }
.osd-top-right { top: 8px; right: 8px; }
.osd-bottom-left { bottom: 8px; left: 8px; }
.osd-bottom-right { bottom: 8px; right: 8px; }

.osd-telemetry-header {
  position: absolute;
  top: 10px;
  left: 28px;
  right: 28px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: #A0AEC0;
  pointer-events: none;
}
.osd-rec-tag { color: var(--ind-status-critical); font-weight: 700; }
.osd-meta { background: rgba(0, 0, 0, 0.6); padding: 2px 6px; border-radius: 2px; }
```

---

## 五、验收标准与执行顺序
1. **执行第一步**：删除 `project-home.desktop.css` 和 `styles.css` 尾部冲突冗余代码，确认 `:root` 变量干净统一。
2. **执行第二步**：用上述一体化 Hero 结构完整替换 `ProjectHome.tsx`，运行并观察 Hero 是否呈现高对比工业座舱与雷达蓝图质感。
3. **执行第三步**：调整 `App.tsx` 中的侧边栏、KPI 仪表卡、高密度数据表格（恢复 13px 正文）和 3D OSD 平显。
4. **编译测试**：运行 `npm run build`，确保 TypeScript 零报错、构建产物无误。
