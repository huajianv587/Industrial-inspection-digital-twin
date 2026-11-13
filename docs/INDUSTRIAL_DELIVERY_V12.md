# 工业巡检系统交付说明 v12

## 交付范围

本版本交付的是一套可在本机运行、可替换现场数据源的工业巡检系统基线，包含：

- 工业站点资产台账：区域、资产、模型来源、巡检点、传感器契约和安全边界。
- 本地虚拟工厂：Blender 生成的米制厂房、管廊、支吊架、容器、换热器、泵组、过滤器、MCC 柜、消防设施、维修工位和天车。
- 巡检执行闭环：航点导航、合成观测、规则评估、异常、人工复核工单和审计数据。
- 多视角制品：GLB、Blend、总览、操作员机位、机器人第一视角、环绕机位、管廊上视和逐航点细节 PNG。
- 后端接口：工业站点台账和 readiness 查询、任务创建、结果入库、制品下载、工单复核和可选 EAM 提交。
- 前端控制台：3D 场景查看、多机位切换、工业资产台账、传感器契约、安全门禁和现场部署阻断项。

## 本机已验证

运行目录：`outputs/industrial-v12/`

- 站点：`IND-PLANT-001`
- 工业资产：10 个
- 巡检航点：10 个
- 传感器契约：4 个
- Blender：5.2.3，本机渲染成功
- 3D 场景：`virtual_world/factory_scene.blend`、`factory_scene.glb`
- 多机位 PNG：总览、操作员、机器人第一视角、10 个环绕机位、10 个航点细节和 10 个航点 RGB 画面
- 运行报告：`inspection_report.md`、`inspection_run.json`、`work_orders/`

可重复命令：

```bash
cd "/Volumes/2T 外设/智能巡逻项目/unitree_isaac_inspection_system"
PYTHONPATH=src .venv/bin/python -m inspection_system.cli validate-industrial-site \
  --config configs/industrial_site_v12.json
PYTHONPATH=src .venv/bin/python -m inspection_system.cli virtual-demo \
  --config configs/industrial_site_v12.json \
  --output-dir outputs/industrial-v12 \
  --render-backend blender
```

## 当前就绪状态

当前状态为 `SIMULATION_READY_FIELD_DATA_PENDING`，不是 `FIELD_READY`。原因是：

1. 全部 10 个模型仍标记为 `procedural_proxy`，没有现场 CAD、点云或校准后的测绘坐标。
2. RGB/热成像目前是合成仿真；压力和振动网关尚未接入。
3. 尚无现场安全验收、机器人调试记录、站点 SAT/FAT 记录或工艺负责人签字。

因此，本版本可以用于流程验收、界面验收、路径规划接口验收和仿真数据链路验收，不能作为真实工厂测量、设备健康诊断或真机安全放行依据。

## 现场替换接口

### 模型与坐标

将 `configs/industrial_site_v12.json` 中的 `model_asset` 替换为已登记的 CAD/点云/资产包 URI，并将 `model_status` 由 `procedural_proxy` 逐项提升为 `field_verified`。每个资产还需要记录：

- 原始文件摘要和版本
- 坐标系、单位和测绘日期
- 资产原点、包络尺寸和维护空间
- 现场复核人、复核时间和变更单号

### 传感器

保留 `sensor_contracts` 的 `sensor_id`、`channel`、`unit`、`calibration` 字段，将 `source_status` 绑定到真实 ROS 2 topic、OPC UA 节点、Modbus 网关或厂商 API。现场数据必须携带时间戳、设备 ID、传感器 ID、标定版本、质量标记和采集帧 ID。

### 机器人

真实 Unitree 或其他四足机器人接入前，需要实现 `RobotAdapter` 契约并通过 ROS 2/Nav2 或厂商 SDK 适配器接入。真机适配器必须提供导航结果、观测来源、坐标系、急停状态和通信健康状态；不能把本地 `VirtualWorldRobotAdapter` 当作真机驱动。

## FAT/SAT 验收门槛

### FAT：工厂验收

- 资产台账与模型版本可追溯，所有航点都能映射到唯一资产。
- 3D 模型、碰撞体、维护空间和禁入区通过人工审查。
- 路线规划不会穿越设备包络、消防通道和受限区域。
- 任务、观测、异常、工单、审计和制品哈希可重复验证。
- 断网、传感器缺失、定位丢失、人员检测和急停条件均能进入安全状态。

### SAT：现场验收

- 使用现场坐标和现场机器人执行低速空载路线。
- 由授权人员确认每个巡检点的可达性、视场、照度和安全距离。
- 逐项校验 RGB、热成像、压力、振动数据的标定和时间同步。
- 以已知工况或受控缺陷验证告警阈值，不能用合成数据替代现场证据。
- 通过安全负责人、设备负责人和运维负责人签字后，才允许进入受控试运行。

## 安全边界

- 系统只生成巡检判断和待复核工单，不自动执行阀门、开关、泄压或其他设备动作。
- `person_detected`、`fire_alarm`、`blocked_egress`、`loss_of_localization` 等条件必须使机器人停止或退出任务。
- `critical_alarm`、疑似泄漏、热斑和消防设施受阻必须人工复核。
- EAM 提交只允许管理员在人工确认后显式触发，不能作为安全联锁。

## 仍需外部资源才能完成的部分

本机无法验证真实工厂扫描、真实 Unitree 动力学、ROS 2 网络、现场传感器标定、Isaac Sim 集群执行、GPU 性能、EAM 厂商接口和现场安全验收。需要现场 CAD/点云、照片或视频、资产清单、机器人型号与 SDK、传感器接口、网络拓扑以及 FAT/SAT 负责人后，才能把 readiness 提升到 `FIELD_READY`。
