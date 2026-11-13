# Unitree Isaac Industrial Inspection Platform

单站点巡检运维平台工程化基线：创建任务、执行器调度、结果校验入库、告警工单人工复核、可选 EAM 提交和审计查询。当前可运行执行器为明确标注的离线合成适配器；Slurm 接口和回传链路已实现，但现有批处理 runner 仍只生成 `synthetic_simulation` 结果。它不代表已运行 Isaac Sim、ROS 2 或真实机器人。

## 本机虚拟世界模式

没有机器狗、Isaac Sim 或 Slurm 时，可以先运行本地虚拟世界闭环。它使用同一份 `configs/site.json`，让程序化占位机器人沿航点执行运动学回放，并用 Blender 建立米制工厂、设备和机器人场景，输出可旋转 GLB、Blender 工程、多机位画面、逐航点 PNG、模拟观测和异常工单；数据仍标记为 `synthetic_simulation`，不是现场测量。

```bash
uv run python -m inspection_system.cli virtual-demo \
  --config configs/site.json \
  --output-dir outputs/virtual-demo \
  --render-backend blender \
  --render-quality production \
  --render-resolution 1280
open outputs/virtual-demo/virtual_world/factory_overview.png
```

`production` 使用 1280 px 画幅宽度和更高的 EEVEE 采样；`preview` 面向快速构图检查；`ultra` 额外提高采样、快速 GI、屏幕光追降噪和阴影池配置，适合输出验收机位。航点 RGB 相机位于四足机器人传感器高度并朝向对应设备，摄影渲染默认不绘制路线箭头和航点文字，导航信息留在 3D 场景/控制台中，避免合成标记覆盖相机证据。可用 `--render-resolution 1920` 提升单帧细节；全套机位耗时随分辨率和设备变化。

如果希望直接在浏览器中创建任务、观察 worker 执行、查看异常工单和浏览虚拟工厂，运行：

```bash
make local-demo
```

它会启动本地 API `http://127.0.0.1:8010`、离线 worker 和 Vite 控制台
`http://127.0.0.1:5173`。创建任务时启用“生成本地虚拟场景”，任务完成后打开任务详情即可旋转/缩放 3D 厂房、播放机器人路线并切换总览、第一视角、环绕和航点相机。Blender 必须已安装；本地演示使用 `outputs/local-demo/inspection.db`、本地制品目录和固定的演示身份，不需要 Supabase 账号；浏览器打开后会直接进入控制台。按 `Ctrl-C` 会同时停止三个进程。

要直接查看已完成的 v16 Ultra 工业场景回放，使用 `make local-demo-v16`。它读取 `outputs/local-demo-v16-ultra/` 中的预渲染任务，控制台内包含 3D 厂房、54 个多机位、机器人第一视角、仓库固定 CCTV 和共用时间轴的同步路线回放；当前产物是本地合成仿真，不是实时视频流。

要查看更高细节的 v17 Ultra 回放，使用 `make local-demo-v17`。它读取 `outputs/local-demo-v17-ultra/` 中的独立预渲染任务，包含 1:1 米制程序化工业厂房、59 个 1280×720 机位、5 个阀门/MCC/泵组/仪表/总览 hero 机位、机器人第一视角、10 个固定 CCTV 和同一条路线时间轴。v17 增加制造表面微细节、冷凝/锈蚀/油污/掉漆见证痕迹以及机器人镜头、激光雷达、维护面板和足部踏面细节；仍然是本地合成仿真，不是实时视频流、真实工厂扫描或真机验收。

继续查看 v18 Ultra 时使用 `make local-demo-v18`。它写入独立的 `outputs/local-demo-v18-ultra/`，在 v17 基础上增加阀门手轮辐条与填料环、法兰垫圈/螺母、压力表玻璃、MCC 柜门锁扣和接地编织带、泵组电机端盖/风扇/润滑点/维护回路，以及 4 个宏观 Hero 机位。v18 仍然是 Blender 程序化代理环境；它不是现场扫描、CAD 对齐、官方 Unitree 资产、真实传感器或部署验收。

继续查看 v19 Ultra 时使用 `make local-demo-v19`。它读取独立的 `outputs/local-demo-v19-ultra/`，在 v18 基础上增加占用中的电缆托盘与固定夹、门式钢架连接板/螺栓、墙面板紧固件、设备区菱形防滑服务板、仪表空气调压器、地漏/清扫口、顶部接线盒与导管下引，并为钢材、管道、柜体、混凝土和铭牌增加中尺度表面 finish 与受控 clear-coat 高光。预置回放包含 63 个机位和同步机器人/CCTV 路线；浏览器预置画面为 768×480 production，Blender 工程保留 v19 Ultra 环境细节。v19 仍然是本地 Blender 程序化仿真，不是现实工厂扫描、CAD 对齐、官方 Unitree 资产、真实传感器或部署验收。

继续查看 v20 Ultra 时使用 `make local-demo-v20`。它读取独立的 `outputs/local-demo-v20-ultra/`，在 v19 基础上增加墙板 gasket 接缝、墙脚湿尘、设备底部积尘与偏移阴影、焊缝热影响区、局部裸钢磨损和维护侧线缆束；预置回放仍包含 63 个机位，并用同一条轨迹时间轴同步机器人 RGB 与仓库固定 CCTV。v20 仍然是本地 Blender 程序化仿真，不是现实工厂扫描、CAD 对齐、官方 Unitree 资产、真实传感器或部署验收。

继续查看 v21 Ultra 时使用 `make local-demo-v21`。它读取独立的 `outputs/local-demo-v21-ultra/`，采用 `factory_environment_v21_ultra` 渲染快照，包含 1:1 米制工厂、63 个多机位、仪表/阀站/MCC/泵组宏观细节、机器人第一视角、仓库固定 CCTV，以及同一条路线时间轴上的同步 RGB/CCTV 捕获；浏览器回放使用 768×480 production 画面，Blender 工程和 GLB 保留完整场景。v21 仍然是本地 Blender 程序化仿真、运动学机器人和合成传感器数据，不是现实工厂扫描、CAD 对齐、官方 Unitree 资产、真实传感器或物理机器狗验收。

继续查看 v22 Ultra 时使用 `make local-demo-v22`。它读取独立的 `outputs/local-demo-v22-ultra/`；首次启动会自动创建一条完整 10 航点任务，并以 768×480 production 画面生成 `factory_environment_v22_ultra` 场景。控制台同步展示机器人路线、机器人 RGB 视角和仓库固定 CCTV 视角，三者使用同一条虚拟时间轴；同时提供可旋转 GLB、多机位画面、Blender 工程和逐航点制品。v22 仍然明确是 Blender 程序化仿真、运动学机器人和合成传感器数据，不是现实工厂扫描、CAD 对齐、官方 Unitree 资产、真实视频流或物理机器狗验收。

继续查看 v23 高颗粒度工业回放时使用 `make local-demo-v23`。它读取已经完成的 `outputs/industrial-v23-full-768/` 预渲染制品并导入独立的 `outputs/local-demo-v23-ultra/`，启动时不会重复执行 Blender 全量渲染。v23 包含 63 个 768×480 多机位、Ultra/256 samples EEVEE 渲染、约 38 MB GLB、Blender 工程、10 个机器人 RGB 与仓库 CCTV 成对捕获，并在控制台中用同一条路线时间轴同步切换地图位置、机器人视角和固定机位。导入器是幂等的；它只复用已生成制品，不改变 v16-v22 输出。v23 仍然是高颗粒度 Blender 程序化仿真、运动学机器人和合成传感器数据，不是现实工厂扫描、CAD 对齐、官方 Unitree 资产、真实视频流或物理机器狗验收。

继续查看 v24 局部任务照明与运维细节回放时使用 `make local-demo-v24`。v24 读取 `outputs/industrial-v24-full-768/` 并导入独立的 `outputs/local-demo-v24-ultra/`，保留 v23 制品不变；它增加阀门、MCC、泵组和仪表的局部任务光、校准见证牌、铆钉和仪表服务回路。同步回放中，机器人 RGB 与仓库 CCTV 会显示同一条路线的帧号和回放时钟。v24 同样是 Blender 程序化仿真，不代表真实工厂、真实传感器或物理机器狗。

继续查看 v25 MCC 服务细节回放时使用 `make local-demo-v25`。v25 读取 `outputs/industrial-v25-full-768/` 并导入独立的 `outputs/local-demo-v25-ultra/`，保留 v23/v24 制品不变；MCC 近景按电源保护区、控制启动区和现场端子区组织，包含母排绝缘支撑、DIN 导轨、线槽、端子排、线号、接地排、柜体密封和 LOTO 服务标识。控制台仍同步展示机器人第一视角、仓库固定 CCTV、路线地图和同一路线帧号；回放是本地运动学仿真与合成传感器数据，不是真实工厂扫描、真实机器狗或实时视频流。

继续查看 v26 开口柜体真实感回放时使用 `make local-demo-v26`。v26 读取 `outputs/industrial-v26-full-768/` 并导入独立的 `outputs/local-demo-v26-ultra/`；MCC 改为开口钣金柜体、凹入式后背板、三相母排绝缘支撑、塑壳断路器、启动器、DIN 模块、端子排、分色控制线、线槽、门铰链、接地排和 LOTO 标识。关键近景、固定 CCTV、3D GLB 和同步机器人/CCTV 回放均切换到 v26；仍然是 Blender 程序化仿真、运动学机器人和合成传感器数据，不是真实工厂扫描、真实机器狗或实时视频流。

继续查看 v27 全厂精细化回放时使用 `make local-demo-v27`。v27 读取 `outputs/industrial-v27-full-768/` 并导入独立的 `outputs/local-demo-v27-ultra/`；在 v26 开口 MCC 基础上补充高位灯具外壳与吊装件、墙面接线盒和导管、地面检修盒与锚栓、PPE/ARC FLASH/EYEWASH 固定标识、机器人充电停靠点，以及 STEAM/CW-RETURN/IA 工艺标签。整套 64 个机位、Blender 工程、GLB、机器人第一视角和仓库固定 CCTV 使用同一套 v27 场景；仍然是 Blender 程序化仿真、运动学机器人和合成传感器数据，不是真实工厂扫描、真实机器狗或实时视频流。

继续查看 v28 机器人头顶视频流回放时使用 `make local-demo-v28`。v28 保留 v27 已验证的完整静态多机位，在场景工程中追加墙板缝、紧固件、线缆入口、地面接缝和航点校准见证牌，并生成 `synchronized_video_manifest.json`、机器人头顶 RGB 图像流和固定 CCTV 图像流。两路画面按同一条运动学路线帧同步，控制台默认以 0.5x 慢速播放并预取下一帧；v28 仍是本地 Blender 合成图像流，不是真实现场视频、真实机器狗或实时传感器。

最终产品演示使用 `make local-demo-v30`，控制台地址为 `http://127.0.0.1:5173/`。场景包位于 `outputs/industrial-v30-final-768/`，独立演示数据库位于 `outputs/local-demo-v30-final/inspection.db`。v30 保留原始 Blender 程序化材质和微几何，并为浏览器 GLB 导出增加稳定的 PBR 兼容材质；工厂总览、64 个多机位、48 帧机器人头顶 RGB 与固定仓库 CCTV 同步图像、214 帧路线回放均可在任务详情中查看。已验证演示任务 `RUN-V30-FINAL-PRODUCT-DEMO-SUCCESS` 为 `SUCCEEDED`，10 个航点均有正常合成观测、0 告警、0 待复核工单。历史命令 `make local-demo-v29` 保留为兼容入口。该系统是本机 Blender 场景、运动学路线和合成数据演示，不代表真实现场部署、安全验收或真实机器人/传感器运行。

当前交付演示使用 `make local-demo-v38`，控制台为 `http://127.0.0.1:5174/`，API 健康检查为 `http://127.0.0.1:8017/healthz`。启动脚本会幂等导入两条隔离任务：`RUN-V38-HQ-SMOOTH-STREAM`（全正常连续流）和 `RUN-V38-SYNTHETIC-ANOMALY`（隔离合成异常闭环），数据库位于 `outputs/local-demo-v38-smooth-stream/inspection.db`，场景制品位于 `outputs/industrial-v38-smooth-stream/`。控制台提供 1:1 米制工厂 3D 场景、64 个多机位、机器人头顶 RGB 与仓库 CCTV 双路连续视频流、214 帧碰撞安全路线、真实俯视平面图、0.5x/0.25x 慢速逐帧回放、证据哈希和人工复核/审计链路；异常分支仅使用本地合成数据，不调用真实 EAM，不触发现场动作。

V38 Chrome 验收命令：

```bash
cd web
LOCAL_DEMO_URL=http://127.0.0.1:5174 LOCAL_DEMO_RUN_ID=RUN-V38-HQ-SMOOTH-STREAM npm run test:demo
LOCAL_DEMO_URL=http://127.0.0.1:5174 LOCAL_DEMO_RUN_ID=RUN-V38-SYNTHETIC-ANOMALY node ./node_modules/@playwright/test/cli.js test --config=playwright.local-demo-v37.config.ts
```

V38 使用独立数据库 `outputs/local-demo-v38-smooth-stream/inspection.db` 和独立媒体目录 `outputs/industrial-v38-smooth-stream/`；双路 Blender 合成视频以 60 FPS 编码，在默认 0.5x 慢放时目标约 30 FPS。V37 的数据库、媒体与运行服务保持不变。V38 同时测量浏览器 Three.js/WebGL 实际帧率，路线标签按点位密度自动避让；仿真流不显示不适用的网络丢包指标。需要回归旧版 V37 时，仍可使用 `make local-demo-v37` 与 `playwright.local-demo-v37.config.ts`。

V38 制品门禁：`make validate-local-demo-v38` 会核对健康检查、正常任务、隔离合成异常任务、64 个多机位、48 个同步源帧、214 帧路线、机器人/CCTV 双路 60 FPS H.264 视频、SQLite 中的 SHA-256 和本地存储对象一致性。该命令只读检查，不修改任务或制品。

所有浏览器验收使用 Chrome 通道；移动端不属于当前交付范围。V37 仍是本机 Blender/Three.js 合成仿真，不等同于真实工厂扫描、真实机器狗、Isaac Sim/ROS 2 现场运行或生产 EAM 接入。

当前强化的桌面演示使用 `make local-demo-v31`，默认控制台为 `http://127.0.0.1:5179/`，API 为 `http://127.0.0.1:8011/healthz`。场景包写入独立的 `outputs/industrial-v31-final-1280/`：主展示和 hero 机位为 1280×720，补齐的环绕/固定机位为 768×480，机器人 RGB/CCTV 同步采样流为 512×288；同时包含工业 HDRI 环境照明、可旋转 GLB 和 Blender 工程。演示数据库和制品位于 `outputs/local-demo-v31-final/`。浏览器 3D 使用同一 HDRI 做金属环境反射，并加入微表面 PBR 细节、软阴影和可验证的屋顶剖视切换。外部 HDRI 的来源、许可和校验和记录在 `web/public/assets/THIRD_PARTY_NOTICES.md`。这些是为产品演示增强的合成场景，不是现实工厂扫描、真机控制、真实传感器视频或生产验收；外部部署门槛仍按 [交付就绪清单](docs/DELIVERY_READINESS.md) 执行。
交付前可运行 `make validate-local-demo-v31`，它会在不修改制品的前提下核对 API 健康、成功任务、10 个航点、0 工单、64 个机位、48 帧同步流、PNG 尺寸、GLB SHA-256 和可用于剖视的屋顶节点。

`local_demo` 是显式 opt-in 的开发环境：它只允许文件型 SQLite、离线合成执行、本地制品存储和开发身份认证，不能被生产配置或 Compose 自动启用。

也可以通过离线 API 创建带渲染的任务，在请求中加入 `"render_backend": "blender"`。worker 会把 `.blend`、`.glb`、总览、第一视角、环绕机位和逐航点 PNG 作为结果制品导入；控制台可在创建任务时启用“生成本地虚拟场景”，在任务详情中直接旋转 `.glb` 并切换多机位截图。API worker 使用 1280 px production 画幅默认值；命令行可选择质量与分辨率。Blender 渲染脚本位于 `blender_sim/render_factory.py`，使用程序化占位设备和机器人，不声称加载了 Unitree 官方资产。

## 架构

- FastAPI + SQLAlchemy 提供任务、结果、工单、制品和审计 API。
- Supabase PostgreSQL 是生产和普通开发环境的数据库；文件型 SQLite 只在显式 `local_demo` 或隔离测试中允许使用。
- Alembic 管理数据库版本；应用启动不会自动建表。
- Supabase Auth 提供用户登录和 JWT；API 只接受受信任 `app_metadata.roles` 中显式分配的 `admin`、`operator`、`reviewer` 或 `viewer`，无有效角色的账号返回 403。生产环境应关闭公开注册。
- React/TypeScript 运维台通过同源 Nginx 访问 API。
- Docker Compose 提供 `migrate`、`api`、`worker`、`web` 服务，不包含 PostgreSQL 容器。
- Compose 默认只把 Web HTTP 端口绑定到 `127.0.0.1`；生产访问必须经过 TLS 反向代理，并由 TLS 入口强制 HTTPS、配置 HSTS 和转发 `X-Forwarded-Proto`。不要直接把 Compose 的 HTTP 端口暴露到公网或局域网。
- 生产 Compose 将制品存入专用 Supabase Storage 私有 bucket；数据库只保存对象引用、来源和 SHA-256。开发测试可显式使用本地文件适配器。

## 配置与部署

需要 Supabase 项目、启用的 Email/Password Auth、Supabase PostgreSQL 连接串，以及 Docker Compose。项目的 Supabase 连接串不要写入代码、镜像或提交记录。

```bash
cp .env.example .env
```

在 `.env` 设置专用 Supabase 项目的 `SUPABASE_DB_URL`（仅 migration 使用的 owner/admin 连接）、`SUPABASE_APP_DB_URL`（API/worker 使用的受限运行角色）、`SUPABASE_URL`、`SUPABASE_ANON_KEY`、`OIDC_ISSUER` 和 `OIDC_AUDIENCE`。首次迁移前先创建 `inspection_app` 最小权限角色；Alembic 会为该角色授权并启用业务表 RLS。数据库连接使用 Supabase TLS 端点；`.env` 已被 Git 忽略。前端只接收 Supabase anon/publishable key，禁止使用 service-role key。给已授权用户在 `app_metadata.roles` 中配置应用角色；不要使用可由用户自行修改的 `user_metadata` 做权限判断。

生产配置必须显式指定 `INSPECTION_EXECUTOR=slurm` 与 `SLURM_RESULT_SOURCE=isaac_sim`，并提供经目标集群验证的 Isaac Sim 版本、机器人资产、适配器和资源配置。Compose 的 `preflight` 服务会使用运行角色与挂载的专用 secrets 执行 `inspection-system validate-runtime`，静态校验生产设置、Slurm 凭据文件、站点配置，以及数据库、OIDC 和 Storage 是否属于同一 Supabase project；只有校验成功后才会运行数据库 migration。Alembic 也会独立核对 owner 连接目标，避免错项目迁移。Preflight 不连接 Supabase/Storage/Slurm，也不证明 Isaac Sim 与集群兼容；后续 migration、服务 readiness 和专用 smoke test 各自验证对应运行态。`.env.example` 将这些门槛留空；`offline`/`synthetic_simulation` 仅用于开发与测试，不会作为生产默认执行链路。Supabase Storage 需要单独创建仅用于对象存储的 Auth 用户，并把其 `app_metadata.inspection_storage` 设为 `service`；账号邮箱与密码放入被忽略的 `secrets/` 文件。启动脚本以短暂 root 初始化阶段把只读 Compose secrets 复制到 tmpfs，再以 `appuser` 启动 preflight、API/worker。

worker 对暂时性结果回传/存储错误保留 `IMPORTING` 状态，并按 `RESULT_IMPORT_RETRY_SECONDS`（默认 60 秒）限制自动重试频率；每次失败都会刷新下一次重试的计时起点。该间隔只控制结果导入，不改变 Slurm 提交恢复策略。

只有配置专用 SSH key、经独立渠道核实并固定的 `known_hosts`、Slurm 用户和远程目录后，才设为 `slurm`，并通过 Slurm Compose overlay 启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.slurm.yml up --build -d
```

可先在宿主机运行 `make preflight`；Compose 启动时也会自动执行相同的静态运行配置检查，失败时不会运行 migration。该检查不提交 Slurm 作业或访问 GPU 节点。

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f migrate api worker
```

Compose 启动时先执行 `alembic upgrade head`，成功后才启动 API/worker。生产环境使用 TLS overlay 由 Caddy 独占宿主机 `80/443`，自动申请并续期证书；Web 只在 Compose 网络内被 Caddy 访问。先将 `.env` 中的 `PUBLIC_HOSTNAME` 指向已解析到部署主机的域名，并设置 `ACME_EMAIL`，确认公网 `80/443` 可达，再启动：

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.tls.yml ps
docker compose -f docker-compose.yml -f docker-compose.tls.yml logs -f caddy migrate api worker
```

只有在厂商 endpoint、审批流程、API key secret、请求/响应字段和外部幂等回放都通过授权验收后，才启用 EAM overlay。将 `EAM_ENABLED=true`、`EAM_BASE_URL` 和 `EAM_API_KEY_SECRET_FILE` 配置完整后运行 `make up-eam`；`make down-eam` 停止该组合。overlay 只打开 EAM adapter，不绕过人工 `ACKNOWLEDGED` 门禁，也不触发机器人或现场设备动作。

Caddy 的证书状态与配置持久化在 Docker named volumes `caddy_data` 和 `caddy_config`；不要删除这两个卷。TLS 配置仅将 Caddy 的 `80/tcp`、`443/tcp` 和 `443/udp` 发布到宿主机。未配置域名或公网入口时，使用基础 Compose 做本机联调：桌面运维控制台默认地址为 `http://localhost:8080/`，`/console` 是兼容入口，中英文项目范围与验证说明位于 `http://localhost:8080/overview`；不可将该 HTTP 地址作为生产登录入口。Nginx 已提供 CSP、X-Content-Type-Options、X-Frame-Options、Referrer-Policy 和 Permissions-Policy；`/healthz` 为存活检查，`/readyz` 同时检查 Supabase 数据库连通性。迁移前应核对 `.env` 中的 Supabase 项目 ref，避免指向其他业务项目。

配置好 `.env` 中的 Supabase runtime 数据库 URL 后，可运行 `make smoke-api` 对当前 API 源码做隔离运行检查。它会在 `127.0.0.1:18011` 临时启动开发模式 API，只检查 `/healthz`、连接 Supabase 的只读 `/readyz` 和未认证 dashboard 的 401，并在结束时关闭进程；不写数据库、不创建巡检任务，也不验证真实用户登录、Storage 对象读写或 Slurm 执行。端口可通过 `API_SMOKE_PORT` 覆盖。

若已创建专用 Supabase 测试用户并配置 `app_metadata.roles`，可另运行 `make smoke-auth-api`。它从被 Git 忽略的 `secrets/` 文件读取测试邮箱/密码，向 Supabase 执行密码登录，再以 access token 只读验证 dashboard、站点、任务和工单 API；不会创建账号、写入任务或输出凭据/token。不要使用生产管理员账户，也不要把测试密码发到聊天或写入仓库。

停止 API、worker 和控制台：

```bash
docker compose down
```

数据库与生产制品保存在 Supabase；此 Compose 配置不创建本地数据库或持久制品卷。运行态下载校验只使用容器临时空间。

## 本地自动化测试

自动化测试通过显式 `APP_ENV=test` 和内存 SQLite 创建隔离数据库，不会连接 Supabase，也不会生成数据库文件。

```bash
uv sync --python 3.12 --extra test
make test
make validate
```

交付前可运行 `make release-audit`，它会执行后端回归、站点配置、离线闭环、确定性软件验收、前端生产构建、桌面浏览器回归、Python/Node 依赖安全审计和 Compose/YAML 静态检查，并生成 `outputs/release_audit.json`。报告会把本地已验证项与 Supabase Auth/Storage、Compose runtime、Slurm/Isaac Sim/ROS 2 和真机/EAM 等外部门禁分开；外部门禁不会被该命令自动启动或伪造为通过。`LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED` 表示本地交付门禁通过，但目标环境验收仍未完成。

测试覆盖离线任务闭环、逐航点结果 schema/身份/时间/规则一致性、Isaac provenance、传感器附件引用、ZIP 路径/尺寸/摘要校验、制品流式存储、幂等键冲突、人工复核、EAM 人工确认门禁/失败重试/幂等提交、审计记录、权限拒绝及数据库地址校验。容器化 Supabase 集成、EAM 厂商回放与远程 Slurm smoke test 需各自的环境访问，不能由本地单测替代。

模型运行时契约位于 `docs/MODEL_RUNTIME_CONTRACT.md`。`inspection-system validate-model --manifest ...` 会严格校验版本化 manifest、权重文件大小和 SHA-256、Python 运行时入口以及可选的输入/输出契约推理。Isaac runner 已有本地模型调用、摘要冻结和 provenance 校验；模型或运行时不可用时 fail closed，不会静默改用规则引擎。当前仓库仍没有训练权重、独立 holdout 评测或真实 Isaac/ROS 2 模型接入证据。

桌面控制台浏览器回归使用隔离的 Supabase Auth/API mock，不访问真实 Auth 或写入 Supabase；它覆盖双语切换、登录授权、创建多航点任务、工单复核/审计、已确认工单提交 EAM、无应用角色拒绝，以及客户端在创建请求响应丢失后跨页面重载复用幂等键，并在 Chromium 1024×768、1280×720 与 1440×900 检查桌面布局。移动端不属于本项目验收范围。安装浏览器后运行 `make test-web`（首次安装：`cd web && npm ci && npx playwright install chromium`）。这些测试验证前端与 API 契约交互，不证明真实 Supabase 登录、worker/Slurm 执行、EAM 厂商写入或结果回传。

## 锁定构建与 CI

Python 容器从 `uv.lock` 安装运行依赖，构建阶段与运行阶段分离；构建工具固定为 uv 0.13.4，Python 基底使用 Dockerfile 中锁定的官方多架构 OCI digest。基底升级应显式审查并通过容器 CI。运行 `make audit-python` 可对锁定的 Python 依赖执行同一安全审计。`.github/workflows/ci.yml` 在 push、pull request 和手动触发时运行后端回归、锁定 Python 依赖安全审计、前端生产构建、桌面 Chromium 回归及 `npm audit --audit-level=moderate` 全量 Node 依赖审计，并构建 API/Web 生产镜像、解析普通与 Slurm Compose 配置。容器门禁只用非敏感占位值做构建和静态解析，不启动服务、不执行 migration；CI 不读取生产 secrets，也不连接 Supabase 或 Slurm。GitHub Actions 上的实际 workflow run 仍需以远程结果确认。

## 本地联调

本地 API 仍连接 `.env` 中的 Supabase PostgreSQL，不会启动本地数据库。`make dev-api` 显式选择 development + offline 合成执行，只用于软件联调；生产 Compose 不接受该模式。先启动 API，再启动 Vite：

```bash
make dev-api
cd web && npm run dev -- --port 5177 --strictPort
```

Vite 将 `/api` 与 `/healthz` 代理到 `127.0.0.1:8010`。本地 API 的制品目录只用于开发联调，数据库记录仍保存在 Supabase；生产 Compose 使用 Supabase Storage 私有 bucket。当前执行器若设为 `offline`，生成结果仍标记为合成数据。

上面的 `make dev-api` 适合已有 Supabase 开发项目的联调；没有云端数据库时使用 `make local-demo`，不要手动把普通 development 配置改成 SQLite。

## 安全与边界

- 不要复用此前在聊天中暴露的集群密码；应轮换并改用最小权限 SSH key 账号。
- 不要在没有专用项目确认时把巡检表迁移到其他 Supabase 项目。
- 仿真 runner 当前输出 `synthetic_simulation`；不得将其写成 Isaac Sim、真机或现场验证结果。
- 温度代理不代表真实红外测温精度；模型训练和独立 holdout 评测尚未完成。
- 工单复核必须由授权人员完成；启用 EAM overlay 后，仅 `admin` 可将已 `ACKNOWLEDGED` 的工单提交到配置的 EAM adapter。提交使用持久化状态、稳定幂等键和失败重试，但当前没有厂商端点、凭据或外部回放证据，不触发真实设备动作。

Supabase 项目隔离、最小权限角色和 Auth 设置见 [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md)。详细状态见 [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [docs/SAFETY_AND_LIMITATIONS.md](docs/SAFETY_AND_LIMITATIONS.md)。

云端迁移与 Slurm 节点只读核验记录见 [docs/INFRASTRUCTURE_VALIDATION.md](docs/INFRASTRUCTURE_VALIDATION.md)。
