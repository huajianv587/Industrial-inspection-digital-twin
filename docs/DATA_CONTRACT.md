# 数据契约（结果 schema v1）

## 任务取消与终态

- `inspection_run.status` 只描述单次执行结果：所有冻结航点都成功时为 `COMPLETED`；任一航点失败或跳过时为 `COMPLETED_WITH_ERRORS`。平台任务状态分别映射为 `SUCCEEDED` 与 `PARTIAL`。部分任务仍导入成功航点的观测和工单；失败/跳过航点必须保留错误原因且不得携带派生观测。
- 结果包校验或导入失败使用 `RESULT_IMPORT_FAILED`，调度/执行失败使用 `FAILED` 或 `TIMED_OUT`，用户取消使用 `CANCELLED`。这些是平台任务状态，不是 `inspection_run.status` 的取值。
- Slurm 任务收到取消请求后进入 `CANCELLING`，并保存 `cancellation_target`：用户取消为 `CANCELLED`、执行超时为 `TIMED_OUT`、连续调度器轮询故障为 `FAILED`。
- `scancel` 返回成功只表示取消命令已受理；worker 持续重试并读取 Slurm 状态，直到调度器终态后才写入目标状态。若 Slurm 已报告 `COMPLETED`，worker 审计取消竞态并校验导入结果。
- `cancellation_target` 只在 `CANCELLING` 期间存在，转入终态后清空；未知或失联观测不得直接解释为任务已停止。

## 观测对象

| 字段 | 类型 | 含义 | 约束 |
|---|---|---|---|
| `sample_id` | string | 唯一样本标识 | 每条记录唯一 |
| `timestamp_utc` | ISO-8601 string | UTC 采集时间 | 必须包含时区 |
| `source` | string | 数据来源 | `synthetic_simulation` / `isaac_sim` / `robot` 等 |
| `robot_id` | string | 机器人 ID | 不能为空 |
| `waypoint_id` | string | 巡检航点 ID | 应关联站点配置 |
| `device_id` | string | 设备台账 ID | 应关联设备表 |
| `pressure_mpa` | number/null | 表计读数 | `null` 表示未获得读数，不是 0 |
| `temperature_c` | number/null | 温度值 | 单位摄氏度；真实测温需校准 |
| `ambient_temperature_c` | number/null | 环境温度 | 可选 |
| `cabinet_door_closed` | bool/null | 柜门状态 | `null` 表示未知 |
| `leak_detected` | bool/null | 泄漏检测结果 | `null` 表示未知 |
| `sensor_confidence` | object | 模态置信度 | 未校准前不可解释为概率 |
| `model_version` | string/null | 感知模型或规则引擎版本 | 未使用模型时为 `null`，不得填写未经部署的版本 |
| `calibration_version` | string/null | 传感器/标定参数版本 | 没有标定证据时为 `null` |
| `quality_flags` | string[] | 质量与边界标记 | 唯一、非空；例如 `SYNTHETIC_INPUT`、`NO_RENDERED_IMAGE` |
| `inference_latency_ms` | number/null | 本次感知推理耗时 | 非负毫秒；未执行推理时为 `null` |
| `domain` | object | 仿真域信息 | 光照、距离、视角等 |

## 巡检结果与回传包

- 结果清单必须关联已提交的 `run_id`、`source`、`config_sha256` 和软件版本；不得用结果包中的站点或设备身份覆盖任务冻结清单。
- `inspection_run.results` 必须按冻结顺序恰好包含每个任务航点一次；`waypoint_id`、`device_id` 和观测中的机器人/来源身份必须一致。`sample_id` 使用 `{run_id}-{序号}-{waypoint_id}`。
- 导航失败或跳过时不得携带观测、评估或工单；成功完成的航点必须携带观测与规则评估。整体 `COMPLETED` / `COMPLETED_WITH_ERRORS` 必须与逐点结果一致。
- 运行开始、结束、观测和工单时间必须带 UTC 时区；结束时间不得早于开始时间，观测和工单时间必须落在运行时间区间内。
- 数值只能是有限数字或 `null`；布尔观测只能是布尔值或 `null`；传感器置信度必须在 `[0, 1]`。`null` 保持未知，不得补成正常值。
- 服务端会按冻结设备规则重新计算 assessment，并核对工单内容；客户端或执行器不能单独提交自相矛盾的评估结果。
- Isaac Sim 观测必须带非空的 `sensor_provenance.sensor_ids` 与 `frame_id`、runtime/version、seed、机器人 USD 路径和原始任务 manifest SHA-256。非空 `temperature_c` 必须标记 `temperature_semantics: simulated_proxy`。每个可选传感器文件必须在对应 observation 的 `sensor_provenance.artifacts` 中登记 `name`、`sensor_id`、`media_type` 和 `timestamp_utc`；文件名以航点 ID 命名空间化，传感器 ID 必须存在于该 observation 的 `sensor_ids`，采集时间必须落在本次运行区间内。所有非必需二进制制品都必须被且仅被一个观测引用。
- v1 回传清单必须包含 `inspection_run.json`、`inspection_report.md` 和 `work_orders.json`。平台核对清单摘要、已存储文件的实际大小与 SHA-256，并确认两个 JSON 制品与导入 body 一致。为限制导入内存，三个必需元数据文件的单文件上限分别为 16 MiB、2 MiB 和 8 MiB；图像、深度、热像等大型二进制制品必须作为独立制品。Slurm worker 将 ZIP 成员分块解压到临时文件，再将二进制文件分块写入对象存储，不整体装入应用内存。

## 工单对象

工单包含 `ticket_id`、创建时间、站点/区域、机器人、航点、设备、严重级别、观测、异常代码、异常消息、建议动作和 `requires_human_review`。结果导入后，工单与制品元数据保存在 Supabase PostgreSQL；生产 Compose 将 JSON/Markdown 和其他二进制制品写入 Supabase Storage 的私有 bucket，并以内容寻址路径和 SHA-256 校验。开发/测试可显式使用本地文件适配器；真实 Storage 对象读写与恢复尚未完成端到端验证。工单首先由本系统人工复核；只有已记录 `ACKNOWLEDGED` 的工单才能由 `admin` 显式提交到可选 EAM adapter。`eam_submissions` 以 `ticket_id` 保存 `PENDING`/`SUBMITTED`/`FAILED`、尝试次数、请求摘要、外部单号和时间，使用稳定的工单幂等键；它不触发机器人或其他现场设备动作。

## 合成数据标签

`generate-data` 生成的 `scenario_label` 由场景生成器赋值，`expected_anomaly_codes` 是生成器设计的期望类别。它们适合验证数据管线、标签格式和后续训练代码能否读取数据，不是独立人工标注，也不能用来宣称真实泛化性能。

## 已实现与后续补充字段

- `frame_id`、相机内外参版本、图像/深度/热像文件路径。
- `model_version`、`calibration_version`、推理耗时和质量标记已进入观测对象；服务端会校验类型、范围和重复标记。
- 传感器丢帧、时间同步误差、软件 commit。
- 标注者、标注版本、复核状态和标签来源。
- `mission_id`、导航耗时、重试次数和失败原因。

## 模型运行时契约

- 模型 manifest 使用独立的 `schema_version=1`，固定 `model_id`、语义化 `model_version`、Python runtime 版本、`module:function` 入口、输入/输出 schema 版本以及模型 artifact 的文件大小和 SHA-256。
- 输入 schema 为 `inspection-model-input/v1`，必须携带样本/航点/设备身份、UTC 时间、传感器来源和有限 JSON 特征；输出 schema 为 `inspection-model-output/v1`，必须携带与输入一致的 `sample_id`、与 manifest 一致的 `model_version` 以及显式的测量、置信度、质量标记和推理耗时字段。
- `ModelRuntime` 对 manifest、artifact、输入和输出执行 fail-closed 校验。模型导入、初始化或推理异常不会自动切换到 `RuleBasedDiagnosticEngine`；调用方必须将该错误作为不可用结果处理。
- 当前仓库只完成契约验证器和本地测试，尚未提供训练权重、独立 holdout 结果或真实 Isaac/ROS 2 推理证据。详见 [MODEL_RUNTIME_CONTRACT.md](MODEL_RUNTIME_CONTRACT.md)。
