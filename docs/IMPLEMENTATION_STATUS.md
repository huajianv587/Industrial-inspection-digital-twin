# 当前交付状态

## 2026-10-28 工业渲染 v15 基线

- Blender 航点 RGB 机位移至机器人传感器高度并朝向设备；第一视角绑定首个巡检目标。摄影渲染默认隐藏路线箭头、航点圈与标签，避免路线 UI 混入相机图像。
- 增加 preview/production 采样档位与 CLI 分辨率选项；默认 production / 1280 px，局部可用 1920 px。API worker 任务同样采用该默认，降低全机位 1920px 渲染的超时风险。
- Blender 5.2.3 完成 3 个 production 机位实渲染并人工检查；产物位于 `outputs/industrial-v15-proof/`。这一轮不是全量 44 机位验收。
- `tests.test_virtual_world`：2/2 通过；Python 文件编译和 CLI help 检查通过。完整 Python/前端回归尚未在本轮重跑。
- v14 全量制品和新 v15 proof 分开保留；v15 当前为渲染与相机基线，不宣称完成真实工厂数字孪生或现场部署。

## 2026-10-27 本机虚拟世界执行模式

- 新增 `VirtualWorldRobotAdapter`：使用同一份 `configs/site.json` 让程序化占位机器人沿航点进行可回放运动学执行，记录轨迹、位姿、事件和虚拟传感器 provenance。
- 新增 `inspection-system virtual-demo` / `make virtual-demo`：在没有机器狗、Isaac Sim、ROS 2、Slurm 或 GPU 的本机生成巡检报告、工单和本地虚拟场景；SVG 可作为轻量回退，Blender 可输出米制 3D 厂房与多机位画面。
- 新增显式 `local_demo` 环境 / `make local-demo`：使用文件型 SQLite、本地制品目录、开发演示身份和离线 worker，启动 API、worker 与浏览器控制台，完成可交互的本机虚拟巡检闭环。
- 离线 API 的 `MissionCreate` 支持 `render_backend=none|svg|blender|auto`；worker 按冻结 manifest 运行本地虚拟世界，逐航点渲染进入结果 bundle、Storage 适配器和制品下载接口；生产/Slurm 配置不允许借此切换执行器。
- `blender_sim/render_factory.py` 提供程序化 Blender 场景：1 Blender unit = 1 m，导出 `.blend`/`.glb`、厂房总览、操作员/机器人第一视角、8 个环绕机位和逐航点 RGB 占位图；机器人是程序化占位模型，不是 Unitree 官方资产。
- 2026-10-27 Blender 闭环复核：本机 Blender 5.2.3 实际生成场景；修复首视角相机进入设备、环绕机位出墙和航点制品重复 provenance 的问题。API/worker 任务 `RUN-12FD8A44163E4373` 实测 `SUCCEEDED`，23 个结果制品可通过 API 列出并下载，包含 GLB、BLEND 和 14 个 PNG 机位；Chromium 实测加载 GLB、显示 Z-up 厂房、切换 14 个相机画面，GLB 带机器人关键帧动画。后端 `189/189`、前端 Playwright `30/30` 和前端生产构建通过。这些是本地软件与合成场景证据，不是 Isaac Sim、ROS 2、Unitree 或现场验收证据。

| 子系统 | 状态 | 说明 |
|---|---|---|
| 离线巡检编排 | IMPLEMENTED | 模拟导航、合成观测、规则诊断、工单与报告 |
| FastAPI 运维 API | LOCAL_DEMO_VERIFIED_SUPABASE_AUTH_E2E_PENDING | `make local-demo` 使用 SQLite + 开发演示身份完成任务、结果、工单、审计与制品 API 闭环；Supabase Auth/Storage 真实登录和对象读写仍未验证 |
| worker 崩溃恢复与 Slurm 取消 | IMPLEMENTED_NOT_CLUSTER_VALIDATED | stale `SUBMITTING` 限次恢复；Slurm 按唯一作业名找回 job ID，或从远端结果包恢复导入；`IMPORTING` 暂时性失败按独立 `RESULT_IMPORT_RETRY_SECONDS`（默认 60 秒）退避，失败刷新重试计时；取消请求在 `sbatch` 执行中仍保留，worker 持续重试 `scancel` 并等待调度器终态；轮询故障和运行超时进入带预期终态的可恢复 `CANCELLING`；真实集群恢复仍未验证 |
| 数据库隔离与 schema migration | CLOUD_VALIDATED_THROUGH_0006_LOCAL_HEAD_0007 | 专用项目历史核验到 `20261021_0006`；本地 head 为 `20261026_0007`，新增 `eam_submissions` 表、索引、RLS 与 `inspection_app` 权限；尚未把 0007 应用到云端 |
| Worker 心跳 | IMPLEMENTED_NOT_RUNTIME_VALIDATED | worker 会记录启动、执行、空闲、异常和停止状态；Supabase `service_heartbeats` RLS 表已迁移；当前没有真实运行实例，dashboard 应显示 `not_seen` |
| Supabase Auth JWT | POLICY_GATE_ADDED_SIGNUP_STILL_OPEN | 有效 token 必须带受信任 `app_metadata.roles`，无角色返回 403；生产 preflight 现只读检查 Auth 设置并要求关闭公开注册、开启邮箱确认。当前项目仍允许注册，故策略检查失败；真实用户登录与角色 API 仍未验证 |
| 桌面项目总览 | IMPLEMENTED_DESKTOP_BILINGUAL | `/overview` 展示中英文项目范围、巡检流程与验证边界；桌面视口已检查 |
| 运维控制台 | IMPLEMENTED_BASELINE | `/` 为默认入口，`/console` 为兼容入口；保留中英文登录与运行指挥、站点配置点位视图、最近任务感知诊断、工单人工复核、审计；启用 EAM 配置后，admin 可提交已确认工单并查看外部单号；场景视图不是 Isaac Sim 实时画面 |
| Docker Compose | STATIC_PREFLIGHT_IMPLEMENTED_NOT_RUNTIME_VALIDATED | `preflight` 静态校验生产配置与 Supabase project ref，并作为 migration 前置依赖；含 migration/API/worker/web、无本地数据库或持久制品卷；基础模式 Web HTTP 仅绑定 `127.0.0.1`，生产 TLS overlay 由 Caddy 独占 `80/443` 并持久化证书状态；Nginx CSP/安全头与静态资源缓存策略已实现；本机缺少 Compose 插件，容器运行态未验证 |
| Slurm SSH/SCP 适配器 | STREAMING_RESULT_IMPORT_IMPLEMENTED_NOT_CLUSTER_VALIDATED | 结果包下载前核对远端大小；ZIP 安全检查、分块解包到临时目录，二进制制品按文件流入 Storage；真实 SSH/SCP 与 Slurm 回传未在集群验证。2026-10-21 使用本机 TC2 key 和严格 host-key 校验时，TCP 连接超时，尚未到认证阶段 |
| Slurm 批处理 runner | SYNTHETIC_ONLY | 合成 runner 执行前验证 run/site/robot/seed/config SHA-256，并输出关联 run_id 的 JSON 开始/结束日志；仍未提交真实 Slurm 作业，也未启动 Isaac Sim/ROS 2 |
| Isaac Sim 场景 | STARTER_SCAFFOLD | 最小几何场景脚本，未加载宇树 USD；runner 已定义带航点/传感器/时间戳来源链路的附件接口，但没有真实相机适配器；TC2 GPU/驱动/Isaac 镜像链路未验证 |
| ROS 2/Nav2 适配 | ADAPTER_IMPLEMENTED_NOT_RUNTIME_VALIDATED | lazy ROS 2 imports、Nav2 `NavigateToPose`、有限重试/取消/超时、观测 provenance 校验和默认 `allow_motion=false` bridge；目标 ROS 2 发行版、Nav2、Unitree 和现场安全链路尚未运行 |
| 视觉模型运行时契约 | IMPLEMENTED_NOT_DEPLOYED | 已实现版本化 manifest、artifact 大小/SHA-256 校验、严格输入/输出 schema、运行时入口校验和 fail-closed CLI；没有训练权重、独立 holdout 评测或真实推理接入 |
| 制品持久化 | CLOUD_BUCKET_POLICY_VALIDATED_NOT_IO_E2E | Supabase S3 adapter、内容寻址键、字节级 SHA-256 校验、bucket 和最小 RLS policies 已实现并在云端核验；Storage 专用 Auth 凭据未配置，真实对象读写、幂等回放和恢复未验证 |
| EAM 集成与真机部署 | EAM_ADAPTER_IMPLEMENTED_VENDOR_NOT_VALIDATED | `eam_submissions` migration、HTTPS Bearer adapter、稳定幂等键、人工 ACK 门禁、失败重试、replay 审计和 admin API 已实现；没有厂商端点/凭据/外部写入证据，真机部署仍未连接 |

`IMPLEMENTED_NOT_CLOUD_VALIDATED` 不表示 Supabase 项目已建表或已完成端到端部署；必须在专用项目上执行并核验迁移和登录后才能升级状态。worker 恢复逻辑目前由 mock/内存数据库回归测试覆盖，不能替代学校 Slurm 集群的真实故障恢复和 smoke job 验证。

## 2026-10-20 软件与云端核验快照

- `make test`：75 项通过；覆盖配置拒绝、离线闭环、未知观测、权限与幂等、结果包校验、worker 故障恢复与心跳、批处理 manifest 完整性及 JSON 日志上下文。
- `cd web && npm run build`：TypeScript 检查与 Vite 生产构建通过。桌面总览页在 Chromium 1440×1000、1280×720 与 1024×768 视口完成中英文截图检查；语言切换、锚点导航、图片加载正常，无桌面横向溢出；移动端不在本次验收范围。
- `make validate`、`make demo`、`make data`、`make evaluate`：均通过。离线运行来源为 `synthetic_simulation`；合成数据 200 行；确定性软件验收 4/4，不是模型精度或现场表现。
- Supabase 只读检查：`alembic current` 为 `20261020_0005`，`alembic check` 无漂移；Storage 验证确认私有 bucket、200 MiB 限制和三条受限策略，heartbeat 表已迁移并启用 RLS。
- 本地 API：`/healthz` 与 `/readyz` 返回 200，未认证 dashboard 返回 401。该快照未验证实际 Supabase 用户登录、Storage 对象读写或带会话的控制台流程。
- 本机没有 Docker Compose 插件且 Docker daemon 未运行；未验证 Compose 启动。Isaac Sim/ROS 2/Slurm 真正执行仍未完成。

## 2026-10-21 Supabase 只读 API 核验

- `make test`：79 项通过；新增生产执行器 fail-closed 与 Isaac 配置启动校验测试。`cd web && npm run build` 通过。
- 生产配置现在拒绝 offline/synthetic 执行；`.env.example` 将 Slurm/Isaac 必填项留空，避免兼容性未验证时误启动。Compose YAML 语法通过 Ruby YAML parser 检查，但本机无 Docker Compose 插件及运行中 daemon，尚未验证实际启动。
- `uv run --env-file .env alembic current`：`20261020_0005 (head)`；`alembic check`：无 schema 漂移。
- 使用当前 API 代码通过进程内 `TestClient` 调用 `GET /api/v1/dashboard`，连接 Supabase runtime URL，返回 HTTP 200，worker 状态为 `not_seen`。该检查覆盖业务表只读查询与 heartbeat 表读取。
- 本次用测试 actor 覆盖认证依赖，因此不证明 Supabase Auth 用户登录或真实 bearer-token 授权；没有写入数据库，也没有启动 worker 或替换现有 API 进程。

## 2026-10-21 产品入口与运行态复核

- 桌面默认路由调整为 `/` 运维控制台登录入口；项目范围说明保留在 `/overview`，`/console` 保持兼容。`cd web && npm run build` 通过；在 Chromium 1440×980 检查了默认登录页与 `/overview`，移动端不在验收范围。
- Supabase Auth session 初始化现在会处理 rejected promise / 返回错误并退出 boot 状态；该异常分支通过 TypeScript/Vite 构建检查，尚无真实 Supabase 用户登录验证。
- 当前本机 API 实测 `/healthz=200`、`/readyz=200`、未认证 `/api/v1/dashboard=401`。这证明服务存活、数据库可达和匿名请求被拒绝，不证明用户登录后业务闭环。
- 8010 端口当前进程启动于 2026-10-20，未重启；本轮显式角色 403 修复已由新代码单测验证，但该进程仍加载旧代码。按现有约束未终止或重启该进程，因此不能把新授权行为视为已在运行实例生效。
- Supabase Auth 只读 settings 查询显示 Email provider 已启用、公开注册当前仍开启、邮件自动确认关闭。API 已改为要求显式可信应用角色；未分配有效 `app_metadata.roles` 的账号返回 403。没有更改云端 Auth 配置；生产启动前仍须关闭公开注册并完成获授权用户登录验证。
- `make test`：80 项通过；`make validate`：配置有效，3 个航点。
- 当前 Docker CLI 没有 Compose 子命令，daemon socket 不可连接；未启动容器。Slurm key 与 pinned `known_hosts` 配置路径在本机均未解析为可读文件，`secrets/` 仅有 `.gitkeep`，因此本次未发起 SSH，也未提交作业。
- 仍未完成：真实 Supabase Auth 用户流与角色 API 验证、Storage 对象读写、Compose 启动、Slurm/Isaac Sim/ROS 2 执行与结果回传、训练模型独立评测、真机和 EAM 集成。

## 2026-10-21 产品回归与云端 Storage 元数据复核

- Storage 验证器此前要求数据库版本必须恰好为 `20261020_0004`，会错误拒绝已包含该迁移的 `20261020_0005 (head)`。现改为沿 Alembic revision ancestry 检查 Storage migration，新增旧版本/后继版本回归测试。
- `make validate-storage` 在当前 Supabase 项目只读验证成功：schema history 包含 Storage migration，私有 bucket 与受限策略符合配置。该命令只查询数据库元数据，不执行对象上传/下载；真实 Storage I/O 仍未验证。

## 2026-10-21 桌面历史记录分页

- Missions、work orders、audit events API 使用时间戳与资源 ID 组成的 keyset cursor，响应以 `X-Next-Cursor` 表示是否存在更早记录；损坏游标返回 422，同时间戳跨页测试无缺失/重复。
- 桌面控制台每次读取 50 条，三类列表均可逐页加载更早记录；8 秒刷新保留已加载历史并按资源 ID 去重。工单复核更新本地已加载记录，导航与待处理总数读取 dashboard 聚合值。
- `make test`：104 项通过；`make test-web`：12 项通过，Playwright Chromium 覆盖 1280×720 与 1440×900，包含中英文分页入口、任务/工单/审计跨页及已加载旧工单复核；`cd web && npm run build` 通过。
- 浏览器回归使用本地 API/Auth mock，仅验证桌面前端交互与分页契约；本次未重连 Supabase、未读写云端数据、未重启既有服务，也未连接 Slurm。生产 executor、Auth/Storage I/O 与 Isaac Sim/ROS 2 集群闭环仍未验收。

## 2026-10-21 锁定容器依赖与持续集成

- Python Dockerfile 改为 multi-stage build：uv 固定为 0.11.32，生产依赖由 `uv.lock` 且通过 `uv sync --locked --no-dev` 安装；最终镜像不带 uv 构建工具。`python:3.12-slim` 仍使用浮动 tag，尚未固定 digest。
- 新增 `.github/workflows/ci.yml`，对 push、pull request 和手动触发分别运行 Python 3.12 后端测试，以及 Node 24 前端构建和桌面 Chromium 回归。现在还会构建 API/Web 生产镜像，并用占位变量解析普通和 Slurm Compose 配置；流程不需要生产 secrets，Auth/API 仍由本地 mock 覆盖。
- `uv lock --check` 通过；在临时 Python 3.12 虚拟环境中按锁安装生产依赖、执行打包后的 `inspection-system validate-config` 和核心依赖导入均通过。`make test`：104 项通过；前端 `npm run build` 通过；`make test-web`：桌面双视口 12/12 通过。
- Docker daemon socket 当前不可用且没有 Compose 插件，因此本地没有构建或启动新镜像；新增的容器构建与 Compose 解析门禁尚无 GitHub 远程运行结果。Supabase Auth/Storage I/O、worker 实例、Slurm 和 Isaac Sim/ROS 2 真实闭环仍未验收。
- `alembic current`：`20261020_0005 (head)`；`alembic check`：无漂移。`make test`：82 项通过；桌面前端生产构建通过。
- 桌面项目总览上的回归测试数更新为本次验收值 82。中英文登录界面已在桌面浏览器核对。
- Docker CLI 存在，但 `docker compose` 插件不可用，且 Docker 服务未验证；未启动或重启容器。当前 8010 API 进程仍是旧进程，本次授权错误码和桌面拒绝状态尚未加载到该运行实例。

## 2026-10-21 桌面总览优化与接口边界回归

- `make test`：87 项通过；新增机器人适配器来源/身份校验和 EAM 人工确认门禁测试。
- `cd web && npm run build`：TypeScript 检查与 Vite 生产构建通过。
- `/overview` 仅调整桌面端首屏纵向节奏，压缩状态栏与 hero 高度；在 1280×720 桌面视口核对下方系统能力区已进入首屏。双语切换与工作流锚点可用；未修改移动端样式。
- 机器人/EAM 代码目前只定义可替换接口与人工确认门禁，没有真机运动控制或企业 EAM 连接。

## 2026-10-21 当前源码 API 运行态 smoke

- 新增 `make smoke-api`：从当前源码临时启动隔离 API，使用 Supabase runtime 数据库 URL，只读验证健康、数据库 readiness 和匿名访问拒绝，结束时自动关闭进程；默认绑定 `127.0.0.1:18011`，可用 `API_SMOKE_PORT` 覆盖。
- 本次 `make smoke-api` 实测 `health=200`、`ready=200`、`anonymous_dashboard=401`；随后确认 smoke 端口已关闭。该检查没有创建任务或写入 Supabase，不验证真实用户登录、角色授权、Storage 对象读写或 worker/Slurm 执行。
- `make test`：87 项通过；`cd web && npm run build` 通过；`make validate` 通过；`make validate-storage` 与 `uv run --env-file .env alembic check` 通过。
- 当前 `.env` 的 `APP_ENV=production` 与 offline executor / local artifact storage 不兼容，当前源码会 fail closed；本地 smoke 显式覆写为 development/offline/local，不代表生产部署配置有效。未修改 `.env`，未重启 8010 旧 API。
- 仍需完成真实 Supabase Auth 用户流与角色 API 验证、Storage 对象 I/O、Compose runtime、Slurm/Isaac Sim/ROS 2 多航点作业及结果回传。当前未配置 Slurm 主机、可用私钥和匹配 host key，也没有 Storage 专用 Auth 凭据。

## 2026-10-21 桌面与 Auth smoke 入口复核

- `make test`：92 项通过；新增 Auth smoke 缺少测试账号文件时不发起网络请求的回归测试。`cd web && npm run build`：TypeScript 与 Vite 生产构建通过。
- `make smoke-api`：当前源码临时实例实测 `health=200`、Supabase `ready=200`、匿名 dashboard `401`；脚本结束后临时端口已关闭。没有创建任务或写入数据库。
- `make smoke-auth-api`：健康、ready 与匿名拒绝检查通过；Auth smoke 因未配置 `SUPABASE_E2E_EMAIL_SECRET_FILE` 而在发出 Supabase Auth 请求前退出。真实用户登录和带角色 API 验证仍未完成；没有使用生产账号。
- 桌面 `/overview` 在 1280×720 浏览器视口核验，中英文切换与更新后的 92 项测试数可见；本轮未修改移动端样式。
- 本轮未重启 8010 旧 API、未修改 `.env`、未连接 Slurm，也未执行 Isaac Sim/ROS 2 作业。Compose runtime、Storage 对象读写、真实 Auth、集群仿真回传仍是未完成验收项。

## 2026-10-21 桌面控制台浏览器回归

- 新增固定版本 `@playwright/test` 桌面端回归：`make test-web` 在 Chromium 1280×720 与 1440×900 各运行 3 条流程，共 6/6 通过；独立 TypeScript 检查也通过。
- 覆盖中英文切换、授权登录、三航点任务请求及幂等键、人工工单确认/审计展示、无应用角色拒绝，并检查控制台各状态无横向溢出。
- Supabase Auth 与 `/api/v1` 全由本地 Playwright route mock 拦截；任务只进入 mock 队列，不触达真实 Supabase，不运行 worker，不产生模拟或现场执行证据。移动端不在测试范围。
- `make test`：92 项通过；`cd web && npm run build`：TypeScript/Vite 构建通过。真实 Supabase Auth、Storage I/O、Compose、Slurm/Isaac Sim/ROS 2 和结果回传仍未验收。

## 2026-10-21 桌面回归与执行器策略修复

- API 将执行后端固定为部署配置；Slurm/Isaac Sim 部署拒绝请求体中的 `offline` 覆盖，返回 422，且拒绝前不写入任务或审计事件。
- `make test`：93 项通过；`make test-web`：Chromium 桌面 1280×720 与 1440×900 共 8/8 通过，包含 `/overview` 首屏与工作流检查；`cd web && npm run build`：TypeScript/Vite 生产构建通过。
- `/overview` 已同步展示 93 项本地回归测试；1280×720 与 1440×900 实际渲染均检查图片、流程跳转、双语和无横向溢出。
- 本轮未调整移动端样式或验收移动端。浏览器回归使用本地 Auth/API mock，不代表真实 Supabase 登录、Slurm 作业或 Isaac Sim 结果回传已完成。

## 2026-10-21 生产启动门禁与项目绑定

- 新增 `inspection-system validate-runtime` / `make preflight`：静态校验生产执行器、Slurm 与 Isaac 配置、凭据文件存在性、站点配置，以及 runtime 数据库、OIDC issuer、Storage endpoint 的 Supabase project 一致性；不会连接 Supabase、Storage 或 Slurm。
- Compose `preflight` 使用运行角色和专用 secrets，成功后 `migrate` 才能执行；Alembic 另外核对 owner URL 与 `SUPABASE_URL` 的 project ref 后才建数据库连接。
- `make test`：100 项通过；`make validate`：3 个航点有效；两份 Compose YAML 均通过 Ruby YAML parser。错项目的 runtime/owner URL、OIDC issuer 与 pooler project ref 均有回归测试。
- 桌面端 `make test-web`：1280×720 与 1440×900 共 8/8 通过；前端生产构建通过。Docker CLI 缺少 Compose 子命令，因此未解析 Compose 插值、构建镜像或验证服务启动；未运行实际 migration。

## 2026-10-21 Supabase 只读复核与桌面交付快照

- `make test`：101 项通过；`make validate`：站点配置有效，3 个航点。两份 Compose 文件通过 Ruby YAML 语法解析。
- 桌面端 `make test-web`：Chromium 1280×720 与 1440×900 共 8/8 通过；`cd web && npm run build` 通过。覆盖桌面中英文、页面导航、图片与横向溢出；移动端不在本项目验收范围。
- Supabase 只读核验：项目 ref `ypytykmpfxvmrgeujsop`；`alembic current` 为 `20261020_0005 (head)`，`alembic check` 无 schema drift；Storage 私有 bucket 与三条预期策略匹配。未执行数据库写入或 Storage 对象读写。
- `make smoke-api`：当前源码临时实例 `health=200`、Supabase readiness `200`、匿名 dashboard `401`；验证后临时端口已关闭。此项未验证真实用户登录，也未写入 Supabase。
- `make preflight` 按设计拒绝当前生产配置，因为 executor 仍为 `offline`；因此 Compose migration 不会启动。未修改 `.env`。当前 Docker CLI 无 Compose 插件，Compose 插值、镜像构建与服务启动均未验证。
- 未重启旧 API（8010）、未连接 Slurm、未提交作业。真实 Supabase Auth 用户流、Storage I/O、Compose runtime、worker 运行、Slurm/Isaac Sim/ROS 2 多航点执行及结果回传仍未验收；不得将本地 mock 或离线结果描述为现场部署表现。

## 2026-10-21 桌面任务提交幂等重试

- 控制台为每个当前用户与任务请求内容保存待确认的 `Idempotency-Key`；网络失败、响应丢失或页面重载后，重试相同请求会复用该键。仅收到 API 成功响应后才删除待确认键；修改站点/航点/seed 后生成独立键。
- 项目总览测试数同步为 `make test` 当前的 101 项。
- 桌面 `make test-web`：Chromium 1280×720 与 1440×900 共 10/10 通过；新增用例模拟服务端已接收任务但客户端响应丢失，再重载页面重试，并断言复用幂等键且只产生一个任务。该交互由本地 API mock 模拟，不是云端端到端证明。
- `cd web && npm run build`：TypeScript 与 Vite 生产构建通过。未改动或验收移动端；未写 Supabase、未重启 API、未连接 Slurm。

## 2026-10-21 多角色授权回归

- OIDC actor 现在保留所有受信任 `app_metadata.roles`；端点通过允许角色集合与 actor 角色集合求交授权，避免 `operator + reviewer` 被压成单一主角色后丢失其中一种权限。审计仍写入确定性的主角色，未提高无关权限。
- `make test`：102 项通过；新增组合角色测试验证 operator 与 reviewer 权限都可用、admin 权限仍拒绝。
- 桌面 `make test-web`：Chromium 1280×720 与 1440×900 共 10/10 通过；`cd web && npm run build` 通过。项目总览计数同步到 102。
- 当前桌面站点 `http://localhost:8080/` 登录入口在 1280×720 与 1440×900 实际浏览器检查通过：主图加载、无横向溢出、无页面脚本错误；`/overview` 实测显示 102。
- 桌面浏览器/Auth/API 测试使用本地 mock；没有验证真实 JWT 用户流，也未修改 Supabase 用户或角色。移动端仍不在验收范围。

## 2026-10-21 Storage I/O 验收入口与桌面总览

- 新增 `make smoke-storage`：先校验 Supabase database/project binding 与 Storage endpoint/bucket 配置，再执行 bucket 探测、固定 smoke 对象上传、同 key 幂等重放、下载和 SHA-256 校验；不写业务数据库。该命令未执行真实云端 I/O。
- Smoke 使用固定 `storage-smoke-v1/<sha256>` 对象并保留单个标记，不要求扩大 Storage 账号权限去删除对象。当前 `secrets/` 仅有 `.gitkeep`，没有 Storage 专用账号凭据，因此未运行 smoke，Storage 对象读写仍为 `NOT_VALIDATED`。
- `make test`：107 项通过；`make validate`：`SIM-FACTORY-001` 的 3 个航点有效；`cd web && npm run build` 通过；`make test-web`：桌面 1280×720 与 1440×900 共 14/14 通过。
- `/overview` 桌面首屏现用配置点位关系图替代通用实验室主图，显示 `configs/site.json` 的三个航点/坐标并注明非实时地图；中英文一致显示 107 项回归测试数。未调整或验收移动端。
- 本轮没有读取 `.env`、写 Supabase、启动/重启 API/Compose、连接 Slurm 或运行 Isaac Sim/ROS 2。真实 Auth、Storage I/O、worker/Compose runtime、Slurm 仿真回传仍未验收。

## 2026-10-21 当前桌面与部署门禁复核

- `make test`：107 项通过；`cd web && npm run build` 通过；`cd web && npm run test:e2e`：Chromium 1280×720 与 1440×900 共 14/14 通过。回归过程中发现总览断言仍期待 104，现已改为当前显示的 107；页面本身未因此改动。浏览器测试使用本地 Auth/API mock。
- 本机 `http://127.0.0.1:8080/` 返回 HTTP 200；在 1440×900 实际检查了登录入口和 `/overview`。概览状态仍明确显示 `OFFLINE`、worker `NOT SEEN`、Isaac Sim/ROS 2 `NOT VALIDATED`、现场 `NOT CONNECTED`。本次仅验收桌面端。
- `make smoke-api` 使用当前源码临时启动 API，实测 `health=200`、Supabase database readiness `ready=200`、匿名 dashboard `401`；测试结束后脚本负责关闭临时 API。此项只读，不代表真实用户认证或巡检任务闭环。
- `make validate-storage` 只读确认项目 `ypytykmpfxvmrgeujsop` 的 schema 到 `20261020_0005`、私有 bucket、大小限制和三条受限策略符合预期；没有上传/下载对象。`make validate` 确认站点配置有效且有 3 个航点。
- `make smoke-auth-api` 的健康、readiness 和匿名拒绝检查通过；随后因未配置位于 `secrets/` 的专用非生产 Supabase 测试账号文件，在发起 Auth 登录前安全退出。`make preflight` 按设计拒绝当前 production + `offline` executor 配置；未修改 `.env` 或绕过 fail-closed 门禁。
- 本机 Docker CLI 存在，但 Compose 插件不可用，且 Docker daemon socket 未启动，故无法构建/启动 Compose 服务。项目 `secrets/` 只有 `.gitkeep`，缺少 Storage 专用 Auth 凭据和 Compose 所需 Slurm secret 文件；TC2 key 与 host-key 记录存在于用户 SSH 目录，但本轮 TCP 连接超时。本轮未运行 Storage I/O、未执行集群命令、未提交作业，也未运行 Isaac Sim/ROS 2。
- 产品级验收仍未完成：真实 Supabase Auth 用户流与权限、Storage 对象读写、Compose runtime/worker heartbeat、兼容性核验后的真实 Slurm 多航点 Isaac Sim/ROS 2 作业与结果导入。现有桌面 mock、静态 preflight 和配置验证均不能替代这些门槛。

## 2026-10-21 桌面路线配置一致性

- `/overview` 站点路线现在直接导入 `configs/site.json`，不再单独硬编码站点 ID、点位数量、顺序和 X/Y 坐标；图形按统一比例投影并居中，图例与点位无障碍标签从同一数据生成。中文区域名使用配置值，英文区域名按 waypoint ID 翻译。
- 桌面 E2E 直接读取站点配置，验证站点 ID、动态航点数、逐点坐标、中英区域名，以及图形横纵跨度与配置坐标比例一致；Chromium 1280×720 与 1440×900 共 14/14 通过。`cd web && npm run build` 通过。
- 本机 Vite `http://localhost:8080/overview` 返回 HTTP 200；实时页面截图确认新配置路线已加载。此变更只保证总览数据与配置一致，不代表实时地图、机器人定位或 Isaac Sim 运行画面。

## 2026-10-21 上传并发与站点指标

- 制品上传路由改为同步 FastAPI handler，使同步磁盘暂存和 boto3 Storage I/O 在线程池执行，不再占用 ASGI 事件循环；分块读取、大小上限、SHA-256、不可变键和数据库事务逻辑保持不变。新增回归测试要求上传 handler 不为 coroutine；现有端到端 API 测试继续验证多制品上传与结果导入。
- `make test`：108 项通过；`cd web && npm run build` 通过；`cd web && npm run test:e2e`：Chromium 1280×720 与 1440×900 共 14/14 通过。
- `/overview` 不再把可过期的单测数量作为产品指标，改为从 `configs/site.json` 动态显示配置航点数；E2E 读取同一配置校验显示值。该项不代表线上运行统计。

## 2026-10-21 桌面验收与结果制品内存控制

- 本轮范围仅包含电脑端；未增加移动端适配。`cd web && npm run build` 通过，桌面 Playwright 在 1280×720 与 1440×900 共 14/14 通过。
- 结果导入对 `inspection_run.json`、`work_orders.json`、`inspection_report.md` 分别限制 16 MiB、8 MiB、2 MiB；其他二进制制品改走 Storage 流式 SHA-256 校验，避免整文件读入 API 内存。
- 新增结果服务回归覆盖：二进制制品走流式校验、篡改内容被拒绝、超限元数据在 Storage 读取前被拒绝。`make test`：111 项通过。
- 以上后端测试使用隔离 SQLite 测试库；未更改生产数据库目标，仍为 Supabase。没有执行真实 Supabase Storage 对象 I/O、Compose 部署或 Slurm/Isaac Sim/ROS 2 作业，端到端工业验收仍未完成。

## 2026-10-21 Slurm 回传流式制品与传感器来源链路

- Slurm worker 先读取远端 ZIP 文件大小并限制下载量；回传包校验成员名、重复项、链接/加密项、文件数、元数据尺寸和总解压尺寸，再分块解压到受控临时目录。临时 ZIP/制品随 import 结束清理。
- Supabase Storage 上传路径支持 `put_file`，worker 逐文件流式写入，不把可选图像/深度制品聚合到 `dict[str, bytes]`；暂时传输/本地 staging 错误保持可重试，无效或缺失结果包转 `RESULT_IMPORT_FAILED`。
- Isaac adapter contract 新增 `WaypointArtifact`，把 artifact 名、传感器 ID、媒体类型和 UTC 时间戳写入对应 observation 的 provenance；结果导入拒绝超出运行区间、重复、缺失或未引用的可选制品。
- 新增 ZIP 路径遍历、分块解包、远端大小、流式 worker 入库和 provenance 引用回归；另验证 Slurm 已完成但缺少结果包会明确进入 `RESULT_IMPORT_FAILED`。`make test`：117 项通过。均为本地测试，不证明真实集群或 Supabase Storage I/O。
- 未改动网页；电脑端范围不变。`cd web && npm run build` 通过，桌面 Chromium 1280×720 与 1440×900 共 14/14 通过；浏览器测试使用本地 Auth/API mock。当前 `http://localhost:8080/` 返回 HTTP 200。
- 真实 Slurm SSH/SCP、Isaac Sim/ROS 2 传感器、Storage 上传下载、Compose runtime 及人工现场验证仍未完成。

## 2026-10-21 结果导入退避与桌面回归

- 为 `IMPORTING` 结果增加独立 `RESULT_IMPORT_RETRY_SECONDS` 配置，默认 60 秒，并在 `.env.example` 与 Compose runtime 环境中透传；不复用 Slurm 提交恢复间隔。每次暂时性导入失败都会刷新 `updated_at`，避免相同错误在每轮 worker 轮询中被重复请求。
- 回归覆盖冷却期内跳过、到期后重试、失败后重新进入冷却期，以及环境变量加载和非正值拒绝。
- `make test`：122 项通过；`make validate`：站点配置有效，3 个航点；`cd web && npm run build` 通过；桌面 Playwright 在 1024×768、1280×720 与 1440×900 共 24/24 通过。浏览器 Auth/API 使用本地 mock，移动端不在验收范围。
- `docker-compose.yml` YAML 语法解析通过；本机不提供 `docker compose` 子命令，本轮未构建或启动 Compose。没有执行 Supabase 写入、Storage 对象 I/O、Slurm/Isaac Sim/ROS 2 作业；端到端工业验收状态不变。

## 2026-10-21 Supabase 结果队列索引部署

- 为 `missions(status, updated_at)` 增加 Alembic migration `20261021_0006`，与 `IMPORTING` 冷却查询的筛选和排序字段一致；SQLAlchemy metadata 同步登记该索引。
- 迁移前只读确认 Supabase 位于 `20261020_0005 (head)`；随后通过项目绑定校验应用迁移。迁移后 `alembic current` 为 `20261021_0006 (head)`，`alembic check` 返回无 schema drift。
- 迁移后只读 API smoke 实测 `health=200`、Supabase database readiness `ready=200`、匿名 dashboard `401`；没有创建业务记录或更改 Auth/Storage 数据。
- 后端回归 `make test`：123 项通过。此证据只覆盖 Supabase schema 与 API/database readiness，不代表真实 Auth、Storage 对象 I/O、worker 容器、Slurm/Isaac Sim/ROS 2 结果闭环或现场部署已验收。
- 1440×900 实际桌面截图复核发现总览页硬编码旧的 `Migration 0005` 文案，现改为不依赖迁移编号的中英双语 schema 核验状态，并加入 E2E 断言。`npm run build` 通过；三档桌面视口 E2E 24/24 通过；8080 页面复核 HTTP 200、无横向溢出和脚本错误。未修改移动端。

## 2026-10-21 桌面总览视觉优化

- `/overview` 在电脑端启用现有工程场景照片作为首屏背景，移除抽象网格纹理；配置路线图、项目核验状态和仿真/现场边界继续来自现有数据与文案。
- 改动仅在 `min-width: 901px` 桌面样式，未调整移动端或登录/API 行为。桌面 Chromium 1024×768、1280×720、1440×900 共 24/24；`npm run build` 通过；1440×900 与 1280×720 截图无横向溢出和页面脚本错误。
- E2E 使用本地 Auth/API mock，照片是工程场景素材，不代表当前站点实景；本次视觉优化不改变真实 Supabase Auth/Storage、Slurm、Isaac Sim/ROS 2 或现场验收状态。

## 2026-10-21 Supabase Auth 生产策略门禁

- 新增只读 Supabase Auth settings 校验：生产 `validate-runtime`/Compose preflight 在迁移前要求 `disable_signup=true`、`mailer_autoconfirm=false`；`make validate-auth` 可单独核验，不读写用户、任务或数据库。
- 当前项目真实检查结果为 `Production requires public Supabase sign-ups to be disabled`，确认公开注册仍开启；未更改 Dashboard 设置。云端关闭注册仍待用户对具体设置变更进行操作时确认。
- `make test`：133 项通过；`make validate` 通过；`make validate-storage` 只读确认 Supabase schema `20261021_0006`、私有 bucket 与受限策略；`alembic check` 无漂移。
- 专用 key + 严格 host-key 的当前 SSH 只读探测仍在连接 `10.96.189.12:22` 时超时。Compose/worker runtime、真实 Auth 用户流、Storage 对象 I/O、Isaac Sim/ROS 2 作业及现场验证仍未完成。

## 2026-10-21 运行配置校验加固

- Runtime settings 现在拒绝 NaN/无穷/非正的轮询、worker heartbeat、Slurm 命令和 Storage Auth 超时；拒绝零/非整数任务超时、非法上传/重试整数，以及超出 `1..65535` 的 Slurm 端口。Isaac Sim CPU 数也必须是合法整数。
- 新增无效配置 fail-fast 回归；保留已有错误消息契约。`make test`：138 项通过；`make validate`：`SIM-FACTORY-001` 与 3 个航点有效。
- 桌面范围不变，本次没有修改网页或移动端；本次未访问/写入 Supabase、未启动 Compose/worker、未连接 Slurm 或运行 Isaac Sim/ROS 2。产品级真实运行验收仍未完成。

## 2026-10-21 Compose 容器日志轮转

- API、worker、Web、迁移和预检容器统一采用 Docker `json-file` 日志轮转：单文件上限 10 MiB，最多保留 5 个文件，避免容器日志在宿主机无限增长。
- 新增 Compose 渲染 JSON 断言，并加入 CI 检查普通配置与 Slurm overlay 合并后的所有服务都保留该轮转策略；断言单测通过。
- 架构文档明确该策略仅限制容器日志，不替代数据库审计记录、业务数据保留或集中式日志监控。
- `make test`：141 项通过。基础/overlay/CI YAML 本机语法解析通过；本机没有 Docker Compose 插件和运行中的 daemon，尚未执行 `docker compose config --format json` 或运行服务，目标环境 runtime 仍待验证。

## 2026-10-21 当前产品门禁复核与依赖审计

- 本轮重跑 `make test`：141 项通过；`make validate`：3 个配置航点有效；`make smoke-api`：`health=200`、Supabase readiness `200`、匿名 dashboard `401`，smoke 进程已退出。
- `make validate-storage` 只读确认项目 `ypytykmpfxvmrgeujsop` 的 schema 为 `20261021_0006`，私有 bucket 和三条预期策略匹配；未执行 Storage 对象读写。
- `make validate-auth` 仍因公开注册开启而失败。`secrets/` 仅有 `.gitkeep`，无 Auth/Storage/Compose 所需凭据；未修改 Supabase Auth 配置。
- `make preflight` 按设计拒绝当前 `.env`：生产环境仍配置为 `INSPECTION_EXECUTOR=offline`，因此没有运行 migration 或启动生产服务。
- 全量 Node 依赖当前 `npm audit --audit-level=moderate` 为 0 vulnerabilities；新增 `npm run audit` 并纳入 Node CI job。工作流本地语法及命令通过后，GitHub Actions 远程 run 仍需确认。
- Docker Compose 插件与 daemon 均不可用。使用 TC2 专用 SSH key、`PasswordAuthentication=no`、严格校验已固定 host key 对 `10.96.189.12:22` 只读连接再次超时；未执行集群命令或提交作业。
- 产品级验收仍未完成：Auth 生产策略与真实用户登录、Storage 对象 I/O、Compose/worker runtime、Slurm/Isaac Sim/ROS 2 多航点作业与结果回传。上述本地/只读检查不升级这些状态。

## 2026-10-21 桌面总览排版与双语细节

- `/overview` 桌面路线图改为浅色高对比工程图，仍由 `configs/site.json` 生成；状态栏、指标区和模块说明加强了字号与层级，缩短首屏高度，让下一段模块内容进入 1024×768、1280×720 和 1440×900 视口。
- 中文界面的模块和区块标签已本地化；Playwright 增加中文/英文标签、路线图配色和首屏可见性断言。`npm run build` 通过，桌面 Chromium E2E 24/24 通过，三档均无横向溢出或页面脚本错误。
- 本轮仅改桌面总览与浏览器测试，没有调整移动端、登录或业务行为。E2E 继续使用本地 Auth/API mock；不改变 Supabase Auth/Storage、Compose/worker、Slurm/Isaac Sim/ROS 2 和现场闭环的未验收状态。

## 2026-10-21 Python 依赖安全门禁

- 将 `uv` 固定版本从 `0.11.32` 提升到 `0.13.4`；该版包含上游修复。锁文件中的 `certifi` 从 `2026.10.18` 升到 `2026.10.19`，避免漏洞数据库对 GHSA/PYSEC 修复版本记录不一致造成的扫描告警。
- CI 新增 `uv audit --locked`；容器构建与后端 CI 使用相同 uv 版本。`uv lock --check` 通过，`uv audit --locked` 报告 48 个解析依赖无已知漏洞。
- 使用临时 Python 3.12.13 环境验证：`make test` 141 项通过，`make validate` 的 3 个航点有效；Node `npm audit --audit-level=moderate` 无漏洞。未覆盖远程 GitHub Actions 实际执行。
- Supabase 只读验证：schema `20261021_0006`、私有制品 bucket 与策略有效；`make smoke-api` 为 health 200、database readiness 200、匿名 dashboard 401。`make validate-auth` 因公开注册开启而失败，`make preflight` 因生产配置仍为 `offline` 而拒绝；未修改云端策略、写入业务数据或启动生产服务。

## 2026-10-21 OCI 基底镜像固定

- API Dockerfile 的 build/runtime 两阶段改为共同使用固定的 Docker Official Image `python:3.12-slim` OCI index digest，避免相同提交在不同日期解析到不同基础层；Registry manifest 确认包含 `linux/amd64` 与 `linux/arm64`。
- Docker build 参数允许在经审查的镜像更新中显式覆盖 digest；README 已更新发布说明。当前本机没有 Docker Compose 插件、Buildx 或可用 daemon，因此没有本地构建镜像；容器 build 的实际验证仍依赖 GitHub Actions runner。

## 2026-10-21 HTTP 暴露面与产品门禁复核

- Compose Web 端口改为仅绑定 `127.0.0.1`，防止未加密 HTTP 直接暴露到局域网/公网；生产需要外部 TLS 反向代理强制 HTTPS、提供 HSTS，并转发 `X-Forwarded-Proto`。Nginx 增加 restrictive CSP、Permissions-Policy、入口页重新验证和 hashed asset 长期缓存；镜像构建执行 `nginx -t`。
- Compose 校验器现在拒绝非回环 Web 绑定及 API/其他服务的宿主机端口；CI 新增容器响应头 smoke。Compose 与 CI YAML 语法检查及静态校验通过；CI 容器 smoke 和 `nginx -t` 尚未实际运行，因为本机无 Docker Compose 插件且 daemon 未启动。
- `make test`：143 项通过；`make validate`：配置有效，3 个航点；`make smoke-api`：health 200、Supabase readiness 200、匿名 dashboard 401。`make validate-storage` 只读确认 schema `20261021_0006` 与私有 bucket/policies。前端 build 通过，桌面 E2E 24/24（1024×768、1280×720、1440×900）。
- Auth 门禁仍因公开注册开启而失败；生产 preflight 仍因 `INSPECTION_EXECUTOR=offline` fail closed；Auth 测试账号与 Storage 凭据缺失，真实 Auth 和 Storage I/O 未验证。专用 key、仅公钥和固定 host key 的 SSH 连接仍在 TCP 阶段超时，未执行集群命令或提交 Slurm 作业。
- 未修改 Supabase Auth 设置、未写业务数据库/Storage、未启动生产 Compose、未运行 Isaac Sim/ROS 2 或现场机器人。产品级端到端验收仍未完成。

## 2026-10-21 Caddy TLS 部署 overlay

- 新增 `docker-compose.tls.yml` 与 `deploy/caddy/Caddyfile`：TLS 模式移除 Web 宿主机端口，由固定 digest 的 Caddy 独占 `80/tcp`、`443/tcp` 和 `443/udp`，证书状态持久化在 `caddy_data` 与 `caddy_config` named volumes。
- 基础 Compose 增加 `backend`/`edge` 网络：API、worker、migration 和 preflight 仅加入 backend，Web 同时加入两网，Caddy 仅加入 edge；基础开发模式仍只将 Web HTTP 绑定到 `127.0.0.1`。
- Compose 校验器、单测和 CI 已增加 TLS overlay 暴露面门禁；`.env.example` 增加 `PUBLIC_HOSTNAME` 与 `ACME_EMAIL`，Makefile 增加 `up-tls`/`down-tls`，README 与架构文档补充生产启动步骤。
- 本轮 `make test`：146 项通过；`cd web && npm run build` 通过；桌面 Playwright 1024×768、1280×720、1440×900 共 24/24 通过；三份 Compose YAML 用本机 YAML parser 解析通过。
- 本机 Docker CLI 没有 Compose 插件，daemon 也不可用，因此未执行 `docker compose config`、Caddy 容器 `caddy validate`、镜像构建或运行态 TLS/证书申请。移动端未修改、未验收；Supabase、Slurm、Isaac Sim/ROS 2 和现场闭环状态不变。

## 2026-10-21 可重复产品交付审计

- 新增 `make release-audit`，统一执行后端回归、站点配置、离线闭环、确定性软件验收、前端生产构建、桌面 Chromium 回归、Python/Node 依赖审计和 Compose/CI YAML 语法检查，并生成 `outputs/release_audit.json`。
- 当前本机审计结果为 `LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED`，本地检查 `9/9` 通过；报告明确列出 Auth、Storage I/O、Compose runtime、Slurm/Isaac Sim/ROS 2 和现场/EAM 的外部证据缺口。运行审计不会启动服务、提交作业、写入 Supabase 或连接机器人。

## 2026-10-26 模型运行时契约与交付门禁复核

- 新增 `inspection_system.perception.model_runtime`：模型 manifest v1 固定模型 ID/版本、Python runtime 版本、入口函数、输入/输出 schema 版本和 artifact 文件；加载时流式核对文件大小与 SHA-256，并拒绝相对路径越界、符号链接、缺失 runtime 或不可调用入口。
- 新增 `inspection-system validate-model --manifest ... [--input ...]`。manifest、输入和输出均采用严格字段集合；模型初始化或推理失败直接返回错误并记录“no fallback”，不会静默转用确定性规则引擎。
- Isaac runner 现在从冻结的任务 manifest 读取五项模型元数据，在创建 Isaac Sim 应用前校验 manifest/artifact 摘要并加载 `ModelRuntime`；航点推理结果会覆盖观测字段并写入 `model_provenance`，模型输入缺失或推理异常按航点失败处理，不回退到规则引擎。结果导入会再次核对模型 provenance；非生产测试配置可不启用模型，生产 Isaac/Slurm 配置必须完整提供模型元数据。
- 新增 Isaac 模型调用、摘要不匹配、无回退、结果 provenance 篡改和配置边界回归；本轮 `make test`：`173/173` 通过；`make test-web`：桌面 Chromium `24/24` 通过；`make release-audit`：本地检查 `9/9` 通过，整体仍为 `LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED`。
- 这轮仍不提供训练模型、独立 holdout 指标、真实 Isaac Sim/ROS 2 推理、Slurm 结果回传、真机安全或 EAM 厂商证据；上述外部验收状态继续保持 `NOT_VALIDATED`，不把本地 adapter 实现误写成现场集成完成。

## 2026-10-26 EAM 提交与 ROS 2/Nav2 适配边界

- 新增本地 Alembic migration `20261026_0007`，为 `eam_submissions` 建立持久化状态、尝试次数、请求摘要、外部单号、时间字段、索引、RLS 和 `inspection_app` 最小权限。云端项目当前仍只确认到 `20261021_0006`；本轮没有执行真实 migration 写入。
- 新增 `HttpEamAdapter` 和 `POST /api/v1/work-orders/{ticket_id}/eam`：只接受 `admin`，只允许已记录人工 `ACKNOWLEDGED` 的工单，使用 HTTPS Bearer、稳定 `Idempotency-Key`，失败可用同一键重试，成功/replay/失败均写审计。列表接口返回持久化 EAM 状态，控制台增加提交、重试和外部单号展示。
- 新增 ROS 2/Nav2 适配器与 `inspection_bridge` service 边界：默认 `allow_motion=false`，高层导航使用 `NavigateToPose`，不提供 raw `/cmd_vel`；定向契约测试覆盖重试、取消、状态机和观测来源校验。未在目标 ROS 2 发行版、Nav2、Unitree 设备或现场安全链路上运行。
- 本轮定向后端测试 `60/60` 通过；最终全量后端回归 `184/184`、前端生产构建通过、桌面 Playwright `27/27`（1024×768、1280×720、1440×900）通过；`make release-audit` 本地检查 `9/9` 通过，整体仍为 `LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED`。
- EAM 厂商 endpoint、凭据、审批映射、外部幂等回放、真实机器人运动、E-stop、碰撞保护、传感器标定、Isaac Sim/ROS 2 集群运行和现场验收仍保持未验证；不得把本地 adapter/mock 证据写成企业或现场集成完成。
