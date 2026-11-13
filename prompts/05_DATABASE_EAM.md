# Phase 5：数据库与 EAM 工单服务

## 目标
实现可追踪、幂等和可恢复的数据持久化与工单服务。数据库与感知算法分层，不把 SQL 拼接进业务节点。

## 建议数据实体
- `sites`、`robots`、`devices`、`waypoints`
- `missions`、`mission_events`
- `observations`、`assessments`
- `work_orders`、`work_order_events`
- `model_versions`、`dataset_versions`、`calibration_versions`

## 关键要求
- 使用 migration 管理 schema，避免只靠手工建表。
- 所有记录以 `run_id`、`mission_id`、`sample_id` 和 `device_id` 关联。
- 工单写入使用幂等键；重试不能重复创建同一工单。
- 对接口设置认证、授权、超时、有限重试和审计日志。
- 大型图像/热像存对象存储；数据库存 URI、hash、时间戳和元数据。
- 密钥只通过环境变量/密钥管理服务注入，不写入代码、配置样例或日志。
- 先实现本地开发数据库和集成测试，再决定生产部署方式。
- 处置动作始终保留人工审核字段，不能由 LLM 直接下发设备控制指令。

## 验收
从干净环境执行 migration；重复提交验证幂等；模拟服务中断后验证恢复；可通过 `run_id` 查到观测、诊断和工单完整链路。
