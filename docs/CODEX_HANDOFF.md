# Codex 交接与验收清单

## 总体规则

- 先阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/DATA_CONTRACT.md`。
- 不要一次性重写整个仓库；按阶段小步实现。
- 每阶段先列计划和改动文件，完成后运行测试并保留日志/结果。
- 禁止把 mock、合成数据或接口骨架说成已完成的 Isaac Sim/真机/数据库功能。
- 新增依赖需固定版本并解释原因；Isaac Sim 代码必须在目标版本实际验证。
- 保留离线模拟适配器，让没有 GPU/Isaac Sim 的环境仍能运行软件测试。

## Phase 0 — 基线与工程质量

- [x] 运行 `make test`（等价 unittest discovery），当前 `187/187` 通过；以 `docs/IMPLEMENTATION_STATUS.md` 最新核验快照为准。
- [x] 运行 `make test-web`：`30/30` 项 Chromium 桌面浏览器回归通过，覆盖 1024×768、1280×720 与 1440×900；Supabase Auth/API 使用本地 mock，不替代云端或集群验收。
- [x] 增加 GitHub Actions 质量门禁，锁定 Python/Node 环境并运行后端、前端构建和桌面浏览器测试；本地等价命令通过，GitHub 上的实际 workflow run 尚未验证。
- [x] 运行 `validate-config`、`demo`、`generate-data`、`evaluate`；生成 JSON/JSONL 可重新解析且来源标记正确。
- [x] 为任务失败、缺失观测、无效配置补充测试。
- [x] 增加结构化 JSON 日志与 `run_id` 等任务上下文关联；formatter、Isaac runner 失败字段和 Slurm runner 执行日志回归测试通过；真实 Slurm 日志尚未验证。
- **验收**：标准库离线测试通过，生成 JSON 可重新解析，来源标记正确。

## Phase 1 — Isaac Sim 场景与传感器

- [ ] 明确 Isaac Sim 版本、GPU/驱动、Unitree Go2/B2 USD 资产来源与许可。
- [ ] 在 `isaac_sim/standalone/` 实现厂房几何、设备 Prim、机器人资产加载和可复现初始状态。
- [ ] 配置 RGB、Depth、RTX LiDAR、IMU，并验证时间戳与坐标系。
- [ ] 通过 ROS 2 Bridge 发布标准消息；记录 topic、频率、frame_id 和 QoS。
- [ ] 对热像区分“仿真温度标签/伪热图”和物理辐射测温。
- **验收**：实际运行日志、场景截图、topic echo、频率与坐标系验证。没有运行就不得标记完成。

## Phase 2 — 合成数据生成（SDG）

- [ ] 用 Omniverse Replicator 生成 RGB 图像、2D 框/掩码/关键点及元数据。
- [ ] 保存 sample_id、场景 seed、相机参数、设备 ID、标签版本和来源。
- [ ] 设计正常/异常类别分布、域随机化范围和困难负样本。
- [ ] 先人工检查 100 张样本，再扩展规模；检查标签与图像同步。
- [ ] 按场景/设备实例/seed 划分 train/val/test，避免相邻帧泄漏。
- **验收**：数据统计、可视化抽检、标签一致性报告、可复现配置。

## Phase 3 — 视觉模型训练与评测

- [ ] 表计检测/关键点模型、柜门状态模型、泄漏疑似检测模型分开训练和评测。
- [ ] 统一推理输出为数据契约，不让下游任务依赖某个 YOLO 版本的内部结果。
- [ ] 温度算法使用校准后的温度矩阵；没有真实辐射温度真值时只报告热区检测。
- [ ] 输出每类指标、混淆矩阵、模型版本、训练 seed、数据版本和推理耗时。
- **验收**：独立 holdout 评测通过；不得只用训练集结果或合成标签一致性宣称泛化。

## Phase 4 — ROS 2 导航与任务状态机

- [ ] 将导航动作封装成适配器，使用 Nav2 `NavigateToPose` Action。
- [ ] 定义导航成功/失败/取消/超时、重试、跳点、回充/终止策略。
- [ ] 明确 map/base_link/odom/sensor frame、时间同步和 QoS。
- [ ] 区分 Nav2 高层导航与 Unitree 专用步态/速度控制接口。
- **验收**：仿真内连续完成多个航点，故障注入测试通过，日志能复现状态流转。

## Phase 5 — 数据库与工单服务

- [ ] 先定义 schema/migration，再实现持久化，不把数据库访问混进感知代码。
- [ ] 为 mission、observation、assessment、work_order 设计关联 ID 和幂等写入。
- [ ] 对工单接口设置认证、权限、超时、重试和审计日志。
- [ ] 图片/热像等大文件存对象存储，数据库存 URI、校验和与元数据。
- **验收**：重复提交不产生重复工单；失败可恢复；可按 run_id 查询完整链路。

## Phase 6 — 集成与部署

- [ ] 提供开发/测试环境安装脚本、配置校验和健康检查。
- [ ] 固定容器/系统依赖版本，记录 Isaac Sim、ROS 2、驱动与 Unitree SDK 版本。
- [ ] 加入运行监控、日志轮转、服务崩溃恢复和数据保留策略。
- [ ] 进行安全评审；未经授权不连接真实设备或现场网络。
- **验收**：从干净环境按文档重建，完成系统回归测试，并归档所有测试结果。

## 交付要求

每个阶段提交：代码差异、运行命令、环境版本、通过/失败测试、已知问题、可复现输出。任何无法验证的功能标记为 `NOT_VALIDATED`，不要用截图或静态 JSON 冒充运行证据。

## Product delivery gate

- [ ] 运行 `make release-audit` 并归档 `outputs/release_audit.json`。
- [ ] 确认报告中的本地检查全部 `PASSED`。
- [ ] 为 Auth、Storage、Compose、Slurm/Isaac Sim/ROS 2 和现场/EAM 分别补齐目标环境证据。
- [ ] 只有全部目标环境门禁完成后，才能把状态从 `LOCAL_VERIFIED_EXTERNAL_VALIDATION_REQUIRED` 升级为可发布。

## 当前延续状态（2026-10-26）

- [x] 本地 EAM adapter：`eam_submissions` migration `20261026_0007`、HTTPS Bearer 请求、稳定 `Idempotency-Key`、人工 `ACKNOWLEDGED` 门禁、失败重试、replay 与审计。
- [x] 控制台 EAM 操作：仅 `admin` 在 EAM 已启用时可提交已确认工单；列表显示提交状态和外部单号；前端 mock 回归已覆盖三档桌面视口。
- [x] ROS 2/Nav2 代码边界：lazy import、`NavigateToPose`、有限重试、取消/超时、观测身份与 provenance 校验，bridge 默认 `allow_motion=false`。
- [ ] 在目标 ROS 2 发行版上执行 `colcon build`、`ros2 interface show`、bridge service 和 Nav2 多航点运行。
- [ ] 将 `20261026_0007` 应用到已核验 Supabase 项目，并执行真实 EAM vendor smoke、幂等回放和审批审计核对。
- [ ] 完成 Unitree 资产、E-stop、碰撞保护、人工接管、传感器标定以及现场/EAM 验收；本地测试不替代这些证据。

## 当前延续状态（2026-10-27）

- [x] 本机虚拟世界执行：新增 `VirtualWorldRobotAdapter`，沿 `configs/site.json` 航点做可回放运动学轨迹，生成虚拟观测、provenance、轨迹和逐航点 SVG 渲染。
- [x] 本地 API/worker 接入：离线任务请求支持 `render_backend=svg|blender|auto`；渲染制品进入结果 bundle 和制品下载接口；控制台创建任务提供本地虚拟场景开关。
- [x] Blender 可选渲染脚本：`blender_sim/render_factory.py` 使用程序化占位设备与机器人生成 PNG；没有 Blender 时 `auto` 回退到零依赖 SVG，显式 `blender` 请求 fail closed。
- [x] 本机验证：虚拟任务 3 个航点完成并生成渲染文件；后端 `187/187`、前端生产构建通过、桌面 Chromium 回归 `30/30`（三档桌面视口）。
- [ ] Blender 实际安装运行、Isaac Sim/ROS 2/机器狗动态学和真实传感器仍未验证；虚拟世界结果只能证明本地软件闭环，不是现场证据。
