# 模型运行时契约

## 目的

模型权重、推理运行时和下游巡检结果必须有可复核的边界。当前仓库实现的是一个**模型运行时契约和验证器**，不是训练好的模型，也不代表模型已经接入 Isaac Sim、ROS 2 或真实机器人。

模型入口由 `inspection-system validate-model` 校验。校验失败时命令返回非零状态；模型不存在、权重摘要不一致、Python 版本不一致、入口不可加载、输入字段不完整或输出不符合契约时，运行时直接失败，不调用规则引擎替代模型推理。

## Manifest v1

模型 manifest 是 JSON object，字段必须严格匹配下面的结构，不允许额外字段：

```json
{
  "schema_version": 1,
  "model_id": "inspection-baseline",
  "model_version": "1.2.3",
  "task": "inspection_observation",
  "runtime": {
    "name": "python",
    "version": "3.12.0",
    "entrypoint": "your_package.model_adapter:build_predictor"
  },
  "input_schema": "inspection-model-input/v1",
  "output_schema": "inspection-model-output/v1",
  "artifact": {
    "path": "inspection-model.bin",
    "sha256": "<64 lowercase hexadecimal characters>",
    "size_bytes": 123456
  }
}
```

`artifact.path` 可以是绝对路径。相对路径必须位于 manifest 所在目录内；符号链接不允许使用。加载时会流式计算 SHA-256，并同时核对文件大小和 manifest 声明。

`runtime.entrypoint` 必须是 `module:function`。该函数接收已核验的 artifact `Path`，返回一个可调用 predictor。模型依赖缺失、入口导入失败或初始化异常都属于不可恢复的模型运行时错误。

## 输入 v1

输入必须是严格 object：

```json
{
  "schema_version": "inspection-model-input/v1",
  "sample_id": "sample-001",
  "timestamp_utc": "2026-10-26T00:00:00+00:00",
  "waypoint_id": "WP_01_PIPE",
  "device_id": "PIPE-01",
  "sensor_provenance": {
    "sensor_ids": ["rgb_camera"],
    "frame_id": "base_link/rgb_camera"
  },
  "features": {}
}
```

时间戳必须是归一化 UTC；传感器 ID 必须唯一且非空；`features` 必须是有限 JSON 数据。原始图像、深度或热像文件应通过已经验证的制品引用链传递，不能把未校验的路径或任意对象直接当作模型输入可信来源。

## 输出 v1

输出必须严格包含以下字段，并且 `sample_id` 与输入相同、`model_version` 与 manifest 相同：

```json
{
  "schema_version": "inspection-model-output/v1",
  "sample_id": "sample-001",
  "model_version": "1.2.3",
  "calibration_version": null,
  "pressure_mpa": null,
  "temperature_c": 43.5,
  "ambient_temperature_c": 25.0,
  "cabinet_door_closed": null,
  "leak_detected": false,
  "sensor_confidence": {"rgb_camera": 0.91},
  "quality_flags": [],
  "inference_latency_ms": 12.5
}
```

数值必须有限，布尔字段只能为布尔值或 `null`，置信度必须在 `[0, 1]`，质量标记必须唯一。`null` 表示未知，不得自动补成正常值。

## 使用方式

只验证 manifest、权重和运行时入口：

```bash
uv run inspection-system validate-model \
  --manifest /path/to/model.json
```

同时用一个输入样本执行一次推理契约检查：

```bash
uv run inspection-system validate-model \
  --manifest /path/to/model.json \
  --input /path/to/input.json
```

该命令输出模型版本、运行时版本、manifest SHA-256 和 artifact SHA-256。它不生成精度指标，也不证明模型在独立 holdout、Isaac Sim、真实传感器或现场环境中有效。

## 当前边界

- 当前规则诊断引擎仍是确定性软件基线，不是模型推理结果。
- 模型运行时契约已经有本地单元测试，但没有已认证训练权重和独立模型评测结果。
- Isaac runner 在任务 manifest 冻结模型配置后，会在创建 Isaac Sim 应用前加载 `ModelRuntime`，并对带有 `domain.model_input` 的航点显式调用 `ModelRuntime.infer()`；异常必须保留为该航点的失败/不可用结果，不能捕获后静默调用 `RuleBasedDiagnosticEngine` 作为替代。
- `model_version`、`calibration_version`、`quality_flags` 和 `inference_latency_ms` 仍需由真实模型/标定运行时产生，未部署时保持 `null` 或明确质量标记。
