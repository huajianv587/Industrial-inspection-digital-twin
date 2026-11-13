# Isaac Sim 连接阶段

当前 `standalone/create_factory_scene.py` 只用于验证 Isaac Sim 可启动并创建基础几何场景。它不会加载官方 Unitree Go2/B2 USD，不会配置相机/雷达/IMU，也不会发布 ROS 2 topic。自定义 `IsaacExecutionAdapter` 可以通过 `WaypointCapture.artifacts` 返回传感器文件；runner 会校验传感器 provenance 并把附件和结果包一起回传，但目前没有真实传感器适配器或 Isaac Sim 运行验证。

## 运行

在安装并正确配置 Isaac Sim 的环境中，使用该版本推荐的 Python 启动器运行脚本，例如：

```bash
/path/to/isaac-sim/python.sh isaac_sim/standalone/create_factory_scene.py --config configs/site.json
```

如果当前版本使用 `isaacsim` 包而不是 `omni.isaac.*` 命名空间，请让 Codex 根据安装版本调整兼容导入，并实际运行验证。

## 下一步

1. 加载已获得授权的 Unitree 资产，记录 USD 路径和版本。
2. 将占位方块替换为实际设备模型。
3. 添加传感器、坐标系、ROS 2 Bridge 与时间同步。
4. 将渲染结果和真值写入 Replicator 数据集。
5. 为每个新模块添加独立 smoke test。
