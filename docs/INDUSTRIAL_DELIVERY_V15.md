# 工业巡检系统交付说明 v15

## 本轮渲染升级

- 航点 RGB 相机改为四足机器人传感器高度，并根据资产类型瞄准对应检查区域；不再把管道设备特写伪装成机器人第一视角。
- 第一视角从巡检路线首航点和首个设备生成，避免固定使用路线终点并仰拍天花结构。
- 摄影机 PNG 默认隐藏路线、箭头、航点圈和文字标记。导航信息仍保留在 3D 场景与控制台路线面板中。
- 材质程序加入更克制的微表面颜色与粗糙度变化，保持结构可读，避免高频噪点造成颗粒脏污感。
- 渲染提供 `preview`/`production` 两档；production 使用 EEVEE 128 samples。CLI 分辨率默认 1280px，支持单独提升至 1920px。
- 每个巡检航点同时生成机器人 RGB 视角和固定仓库 CCTV 视角；两张图使用同一个轨迹索引和 Blender 帧号，控制台可以沿同一时间轴切换。
- 相机 manifest 记录渲染质量、导航覆盖物、实际渲染机位、航点同步帧和成对制品，便于制品追踪与回归验收。

## 验收证据

- Blender 5.2.3 本机以 production / 1280px 对总览、机器人第一视角、`WP_01_PIPE` RGB 和对应固定 CCTV 机位完成渲染；PNG、`.blend`、`.glb` 和 camera manifest 位于独立验收目录。
- 验收检查包括：固定 CCTV 的相机位置和朝向在航点间保持不变；机器人 RGB 与 CCTV 共享同一个轨迹帧；摄影图不叠加合成导航线；保存的 `.blend` 从第 1 帧打开。
- 该基线由 `industrial-v14` 场景输入生成，保留旧版 v14 交付目录，不覆盖既有产物。

## 复现

```bash
PYTHONPATH=src .venv/bin/python -m inspection_system.cli virtual-demo \
  --config configs/industrial_site_v12.json \
  --output-dir outputs/industrial-v15 \
  --render-backend blender \
  --render-quality production \
  --render-resolution 1280
```

只做构图预览时使用 `--render-quality preview`。可用 `--render-resolution 1920` 提升像素密度；完整机位集渲染耗时显著更高。

## 已知边界

本地模型仍为程序化场景，不是现场扫描、CAD 对齐、实物照片材质采样或 Unitree 官方机器人资产；CCTV 当前是按航点生成的固定机位同步快照，不是连续视频流；运动学回放不包含足端接触、碰撞与动力学。它可以验证工业巡检软件的本地流程、路线可视化和相机布局，不能作为真实现场测量或真机安全验收。
