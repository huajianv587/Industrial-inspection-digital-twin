# 工业巡检系统交付说明 v16

## 本轮渲染升级

- 保留 v15 的米制工厂、工业设备、仪表、阀门、管廊、线缆桥架、消防/维修设施、路线和多机位结构，不覆盖旧产物。
- 新增 `ultra` 渲染档，兼容 Blender 5.2.3 当前实际暴露的 `BLENDER_EEVEE` 引擎；不再只针对不存在的 `BLENDER_EEVEE_NEXT` 设置采样。
- ultra 档写入并实际应用 256 render samples、2048 shadow pool、4 shadow rays、增强 Fast GI、屏幕空间光追和 ray tracing denoise（具体是否生效以 `factory_camera_manifest.json` 的 `render_settings` 为准）。
- ultra 档将曝光从 `-0.55` 调整为 `-0.30`，保留 AgX 色调管理，提升室内设备标签、仪表盘面和地面服务设施的可读性。
- 固定仓库 CCTV 仍是单一固定高位机位，但从厂房中线移到东南侧并略向 MCC 侧取景，减少中央门式立柱对 MCC 和主巡检通道的遮挡；10 个航点仍共享该固定相机的空间姿态。
- manifest 新增真实生效的 `render_engine`、`render_samples` 和 `render_settings`，用于区分“请求质量档”和“Blender 实际配置”。

## 复现

```bash
PYTHONPATH=src .venv/bin/python -m inspection_system.cli virtual-demo \
  --config configs/industrial_site_v12.json \
  --output-dir outputs/industrial-v16-ultra \
  --render-backend blender \
  --render-quality ultra \
  --render-resolution 1920
```

## 同步回放边界

控制台的同步回放继续使用同一条本地运动学时间轴驱动路线、机器人 RGB 航点视角和固定仓库 CCTV 航点快照；manifest 对每个成对机位记录 `same_route_frame: true`。这验证的是本地仿真中的路线与多视角时间对齐，不是实时 CCTV 视频流，也不是现场机器人或真实工厂数据。

## 验收边界

v16 仍是程序化虚拟工厂，不是现场扫描、CAD 对齐、实物照片材质采样或 Unitree 官方机器人资产。渲染质量升级不等于真实传感器标定、碰撞动力学、Isaac Sim/ROS 2 集群执行或现场安全验收已经完成。
