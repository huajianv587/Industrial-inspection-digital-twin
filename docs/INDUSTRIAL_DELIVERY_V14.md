# 工业巡检系统交付说明 v14

## 交付范围

v14 是在 v13 设备、仪表和管线细节基础上继续深化的本地工业巡检仿真基线。新增内容集中在现场施工关系和可检视性：

- 梯式电缆桥架：底板、侧栏、横档、吊架和现场下引束线。
- 仪表风主管：主管、支路、隔离阀、支撑和 IA 标识。
- 结构施工细节：门式刚架柱脚底板、锚栓、设备基础和检修边界柱。
- 地面服务系统：铸铁排水沟、格栅槽、清扫口和维护通道。
- 工艺附件：泄放支路、PSV 标识、蒸汽疏水器、排凝支路和流向标识。
- 现场可视化：总览、资产地图、电缆桥架、仪表风、地面服务、阀组和电气边界专用机位。

## 本机已验证

运行目录：`outputs/industrial-v14/`

- 站点：`IND-PLANT-001`
- 工业资产：10 个
- 巡检航点：10 个
- 传感器契约：4 个
- Blender：5.2.3，本机渲染成功
- 3D 场景：`virtual_world/factory_scene.blend`、`factory_scene.glb`
- 多机位制品：厂房总览、资产地图、操作员/机器人视角、管廊上视、设备细节、桥架、仪表风、地面服务、阀组、电气边界和环绕机位
- 运行制品：`scene_input.json`、`inspection_run.json`、`inspection_report.md`、`work_orders/`

可重复命令：

```bash
cd "/Volumes/2T 外设/智能巡逻项目/unitree_isaac_inspection_system"
PYTHONPATH=src .venv/bin/python -m inspection_system.cli validate-industrial-site \
  --config configs/industrial_site_v12.json
PYTHONPATH=src .venv/bin/python -m inspection_system.cli virtual-demo \
  --config configs/industrial_site_v12.json \
  --output-dir outputs/industrial-v14 \
  --render-backend blender
```

## 当前就绪状态

当前状态为 `SIMULATION_READY_FIELD_DATA_PENDING`，不是 `FIELD_READY`。

1. 10 个资产仍是 `procedural_proxy`，未绑定现场 CAD、点云、照片测量或校准坐标。
2. RGB/热成像仍是合成仿真；压力和振动网关未接入。
3. 当前四足机器人是本地程序化运动学占位体，不是实际 Unitree 资产，也未验证 Isaac Sim、ROS 2、动力学、碰撞和现场安全。
4. 没有现场 FAT/SAT、标定记录、受控缺陷样本或工艺负责人签字。

因此，本版本适合验证工业巡检流程、资产与航点映射、视角覆盖、制品链路和本地控制台，不代表真实现场测量、设备健康诊断或真机安全放行。

## 现场替换门槛

进入现场导入前，需要逐资产补齐：原始模型摘要、坐标系和单位、测绘日期、资产原点、包络尺寸、维护空间、现场照片、复核人和变更单号。传感器需要绑定真实 ROS 2、OPC UA、Modbus 或厂商 API，并保留时间戳、标定版本、质量标记和采集帧 ID。

真机接入必须实现 `RobotAdapter`，通过 ROS 2/Nav2 或厂商 SDK 提供导航结果、观测来源、坐标系、急停状态和通信健康状态；不能把 `VirtualWorldRobotAdapter` 当作真机驱动。

自动执行阀门、开关、泄压和其他设备动作仍然关闭。人员检测、火警、通道阻塞、定位丢失、疑似泄漏和热斑均必须进入停止或人工复核流程。
