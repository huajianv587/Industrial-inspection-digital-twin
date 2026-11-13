from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .config import ConfigError, load_site_config, waypoints_from_config
from .industrial import industrial_readiness, load_industrial_site
from .adapters.simulation import SimulatedRobotAdapter
from .simulation import VirtualWorldRobotAdapter
from .evaluation import run_acceptance_suite, write_acceptance_report
from .mission.orchestrator import MissionOrchestrator
from .platform.auth_policy import validate_supabase_auth_policy
from .platform.settings import Settings
from .perception.model_runtime import ModelRuntime, ModelRuntimeError
from .synthetic import generate_dataset, write_jsonl

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inspection-system",
        description="离线工业巡检闭环基线（模拟数据，不连接真机）")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config", help="检查站点 JSON 配置")
    validate.add_argument("--config", default="configs/site.json")
    industrial = sub.add_parser(
        "validate-industrial-site",
        help="检查工业资产台账、模型来源、传感器契约与安全边界",
    )
    industrial.add_argument("--config", default="configs/industrial_site_v12.json")
    sub.add_parser("validate-runtime", help="启动前检查部署配置与站点配置")
    sub.add_parser("validate-auth-policy", help="只读检查 Supabase Auth 生产策略")
    model = sub.add_parser(
        "validate-model",
        help="校验版本化模型 manifest、权重摘要、运行时入口和可选推理输入",
    )
    model.add_argument("--manifest", required=True)
    model.add_argument(
        "--input",
        dest="input_path",
        help="可选的 inspection-model-input/v1 JSON 文件；提供后执行一次严格推理",
    )
    demo = sub.add_parser("demo", help="运行模拟巡检并输出工单与报告")
    demo.add_argument("--config", default="configs/site.json")
    demo.add_argument("--output-dir", default="outputs/demo")
    demo.add_argument("--fail-waypoint", action="append", default=[],
                      help="模拟导航失败的航点 ID；可重复指定")
    virtual = sub.add_parser(
        "virtual-demo",
        help="在本地虚拟世界中执行巡检并生成 SVG 或 Blender 渲染制品",
    )
    virtual.add_argument("--config", default="configs/site.json")
    virtual.add_argument("--output-dir", default="outputs/virtual-demo")
    virtual.add_argument("--seed", type=int, default=42)
    virtual.add_argument("--render-backend", choices=("svg", "blender", "auto"), default="auto")
    virtual.add_argument("--render-quality", choices=("preview", "production", "ultra"), default="production")
    virtual.add_argument("--render-resolution", type=int, default=1280)
    virtual.add_argument("--fail-waypoint", action="append", default=[],
                         help="模拟导航失败的航点 ID；可重复指定")
    data = sub.add_parser("generate-data", help="生成结构化合成 JSONL 数据")
    data.add_argument("--config", default="configs/site.json")
    data.add_argument("--count", type=int, default=200)
    data.add_argument("--seed", type=int, default=42)
    data.add_argument("--output", default="outputs/synthetic_dataset.jsonl")
    evaluate = sub.add_parser("evaluate", help="运行固定软件验收用例")
    evaluate.add_argument("--config", default="configs/site.json")
    evaluate.add_argument("--output", default="outputs/acceptance_report.json")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-runtime":
            settings = Settings.from_env()
            settings.validate()
            if settings.environment == "production":
                validate_supabase_auth_policy(
                    settings.supabase_url or "", settings.supabase_anon_key or "")
            config = load_site_config(settings.site_config_path)
            waypoints = waypoints_from_config(config)
            print(
                f"部署配置有效：环境={settings.environment}，执行器={settings.executor_mode}，"
                f"来源={settings.slurm_source}，站点={config['site_id']}，"
                f"航点={len(waypoints)}。"
            )
            return 0
        if args.command == "validate-auth-policy":
            settings = Settings.from_env()
            settings.validate_database()
            settings.validate_supabase_project_binding(required=True)
            validate_supabase_auth_policy(
                settings.supabase_url or "", settings.supabase_anon_key or "")
            print("Supabase Auth 策略有效：公开注册已关闭，邮箱确认已开启。")
            return 0
        if args.command == "validate-industrial-site":
            industrial_site = load_industrial_site(args.config)
            readiness = industrial_readiness(industrial_site)
            print(json.dumps({
                "site_id": industrial_site["site_id"],
                "site_name": industrial_site["site_name"],
                "readiness": readiness,
                "config": str(Path(args.config).resolve()),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate-model":
            runtime = ModelRuntime.load(Path(args.manifest))
            output = None
            if args.input_path:
                try:
                    input_payload = json.loads(
                        Path(args.input_path).read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ModelRuntimeError(
                        "模型输入文件无法读取或不是有效 JSON。"
                    ) from exc
                output = runtime.infer(input_payload)
            result = {
                "model_id": runtime.manifest.model_id,
                "model_version": runtime.manifest.model_version,
                "runtime": f"{runtime.manifest.runtime_name}/{runtime.manifest.runtime_version}",
                "artifact_sha256": runtime.manifest.artifact.sha256,
                "artifact_size_bytes": runtime.manifest.artifact.size_bytes,
                "manifest_sha256": runtime.manifest.manifest_sha256,
                "inference": output,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        config = load_site_config(args.config)
        waypoints = waypoints_from_config(config)
        if args.command == "validate-config":
            print(f"配置有效：{config['site_id']}，{len(waypoints)} 个巡检航点。")
            return 0
        if args.command == "demo":
            adapter = SimulatedRobotAdapter(config["robot"]["robot_id"],
                                            set(args.fail_waypoint))
            orchestrator = MissionOrchestrator(
                config["site_id"], config["robot"]["robot_id"], waypoints, adapter=adapter)
            run = orchestrator.run(args.output_dir)
            print(f"运行状态：{run.status}")
            print(f"巡检航点：{len(run.results)}；工单：{sum(r.work_order is not None for r in run.results)}")
            print(f"报告：{Path(args.output_dir) / 'inspection_report.md'}")
            print("注意：这是离线模拟结果，不是真实工厂或真机验证。")
            return 0 if run.status == "COMPLETED" else 2
        if args.command == "virtual-demo":
            adapter = VirtualWorldRobotAdapter(
                site_id=config["site_id"],
                robot_id=config["robot"]["robot_id"],
                waypoints=waypoints,
                output_dir=Path(args.output_dir),
                seed=args.seed,
                render_backend=args.render_backend,
                render_quality=args.render_quality,
                render_resolution=args.render_resolution,
                fail_waypoints=set(args.fail_waypoint),
            )
            run = MissionOrchestrator(
                config["site_id"], config["robot"]["robot_id"], waypoints,
                adapter=adapter,
            ).run(args.output_dir)
            print(f"虚拟世界运行状态：{run.status}")
            print(f"渲染后端：{adapter.resolved_backend}")
            print(f"巡检航点：{len(run.results)}；工单：{sum(r.work_order is not None for r in run.results)}")
            overview_name = "factory_overview.png" if adapter.resolved_backend == "blender" else "overview.svg"
            print(f"总览场景：{Path(args.output_dir) / 'virtual_world' / overview_name}")
            print("注意：这是本地虚拟世界执行，不是真实 Isaac Sim、ROS 2 或机器狗测量。")
            return 0 if run.status == "COMPLETED" else 2
        if args.command == "generate-data":
            records = generate_dataset(waypoints, config["robot"]["robot_id"], args.count, args.seed)
            count = write_jsonl(records, args.output)
            print(f"已写入 {count} 条合成结构化样本：{args.output}")
            print("数据没有真实图像；标签由场景生成器赋予，不可作为真实模型精度证据。")
            return 0
        if args.command == "evaluate":
            report = run_acceptance_suite(args.config)
            write_acceptance_report(report, args.output)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["checks_passed"] == report["checks_total"] else 2
    except (ConfigError, ModelRuntimeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
