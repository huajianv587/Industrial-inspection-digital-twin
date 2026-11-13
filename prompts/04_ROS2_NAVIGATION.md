# Phase 4：ROS 2 导航与巡检状态机

## 目标
将当前 `SimulatedRobotAdapter` 替换为可注入的 ROS 2 适配器，但保留离线适配器供 CI 使用。

## 要求
- 使用 Nav2 `NavigateToPose` Action 完成航点导航；不要用一次性 `/cmd_vel` 直推替代完整导航。
- 定义 `PLANNED → NAVIGATING → INSPECTING → COMPLETED/FAILED` 状态和合法转换。
- 覆盖导航拒绝、取消、超时、失败、传感器无数据、感知服务不可用、工单服务超时。
- 定义每个失败的重试次数、等待时间、是否跳点和任务终止规则。
- 明确 `map`、`odom`、`base_link` 和传感器 frame 的 TF 关系，记录消息时间戳和 QoS。
- Nav2 是高层导航；Unitree SDK2/底层步态控制是另一层，需使用官方支持接口并单独验证。
- 不允许绕过急停、碰撞保护或机器人厂商的安全机制。

## 验收
在 Isaac Sim 中连续执行多航点；注入失败并证明状态机能恢复或安全终止；保存 rosbag/日志和版本信息。离线 CI 仍须通过。
