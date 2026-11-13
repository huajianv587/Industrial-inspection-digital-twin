from __future__ import annotations
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any
from .models import InspectionRun, WorkOrder

def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value

def write_json(path: str | Path, payload: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

def render_work_order_markdown(order: WorkOrder) -> str:
    lines = [
        f"# 巡检工单 {order.ticket_id}", "",
        f"- **级别**：{order.severity.value}",
        f"- **设备**：{order.device_name} (`{order.device_id}`)",
        f"- **区域**：{order.zone}",
        f"- **航点**：`{order.waypoint_id}`",
        f"- **机器人**：`{order.robot_id}`",
        f"- **来源**：`{order.source}`",
        f"- **生成时间（UTC）**：{order.created_at_utc}",
        f"- **需要人工复核**：{'是' if order.requires_human_review else '否'}", "",
        "## 观测数据", "", "| 指标 | 值 |", "|---|---|",
    ]
    for key, value in order.observations.items():
        lines.append(f"| `{key}` | `{value}` |")
    lines += ["", "## 规则告警", ""]
    if order.anomaly_messages:
        lines.extend(f"- {message}" for message in order.anomaly_messages)
    elif order.source == "robot":
        lines.append("- 现场机器人数据需结合传感器标定和现场验收记录复核。")
    else:
        lines.append("- 当前规则未发现超阈值项。")
    lines += ["", "## 建议动作", ""]
    lines.extend(f"{index}. {action}" for index, action in enumerate(order.recommended_actions, 1))
    lines += ["", "> 说明：本工单由模拟输入和规则基线生成，不是现场诊断；处置前必须按现场规程复核。", ""]
    return "\n".join(lines)

def render_run_markdown(run: InspectionRun) -> str:
    if run.source == "isaac_sim":
        title = "# Isaac Sim 仿真巡检报告"
        disclaimer = (
            "> 本报告来自 Isaac Sim 仿真。温度值仅为仿真代理数据，不代表真实红外测温或现场表现。"
        )
    else:
        title = "# 工业厂区模拟巡检报告"
        disclaimer = (
            "> 本报告由离线模拟适配器生成。数值和异常状态用于验证软件流程，"
            "不代表真实工厂测量或模型精度。"
        )
    lines = [
        title, "",
        f"- **运行编号**：`{run.run_id}`",
        f"- **站点**：`{run.site_id}`",
        f"- **机器人**：`{run.robot_id}`",
        f"- **状态**：`{run.status}`",
        f"- **开始时间（UTC）**：{run.started_at_utc}",
        f"- **结束时间（UTC）**：{run.finished_at_utc}",
        f"- **数据来源**：`{run.source}`", "",
        disclaimer, "",
        "## 航点结果", "",
        "| 航点 | 设备 | 导航 | 巡检 | 级别 | 异常代码 |",
        "|---|---|---|---|---|---|",
    ]
    for result in run.results:
        severity = result.assessment.severity.value if result.assessment else "UNKNOWN"
        codes = ", ".join(a.code for a in result.assessment.anomalies) if result.assessment else "-"
        lines.append(f"| {result.waypoint_id} | {result.device_id} | {result.navigation_status} | "
                     f"{result.inspection_status} | {severity} | {codes or '-'} |")
    lines += ["", "## 工单索引", ""]
    orders = [r.work_order for r in run.results if r.work_order is not None]
    if orders:
        lines.extend(f"- `{o.ticket_id}` — {o.device_name} — **{o.severity.value}**" for o in orders)
    else:
        lines.append("- 本次没有生成工单。")
    lines.append("")
    return "\n".join(lines)

def write_run_artifacts(run: InspectionRun, output_dir: str | Path) -> dict[str, str]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    run_json = base / "inspection_run.json"
    run_md = base / "inspection_report.md"
    write_json(run_json, run)
    run_md.write_text(render_run_markdown(run), encoding="utf-8")
    orders_dir = base / "work_orders"
    orders_dir.mkdir(parents=True, exist_ok=True)
    for result in run.results:
        if result.work_order is None:
            continue
        order = result.work_order
        write_json(orders_dir / f"{order.ticket_id}.json", order)
        (orders_dir / f"{order.ticket_id}.md").write_text(
            render_work_order_markdown(order), encoding="utf-8")
    return {"run_json": str(run_json), "run_markdown": str(run_md), "work_orders_dir": str(orders_dir)}
