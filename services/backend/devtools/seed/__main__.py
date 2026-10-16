from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from backend_app.core.config import get_settings
from backend_app.core.errors import AppError
from backend_app.core.redis import get_redis
from backend_app.db.session import get_engine, get_session_factory
from devtools.seed.bootstrap import SeedSettings
from devtools.seed.config import REGISTRY, SeedError, resolve_plan
from devtools.seed.repository import coverage, database_fingerprint
from devtools.seed.runner import run

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="仅开发环境：通过业务 Service 追加数据并支持续跑")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="列出场景、数量参数和默认值")
    commands.add_parser("coverage", help="只读检查实际数据库的表覆盖")
    for name in ("plan", "run"):
        command = commands.add_parser(name, help="估算规模" if name == "plan" else "追加新批次")
        selection = command.add_mutually_exclusive_group(required=True)
        selection.add_argument("--all", action="store_true")
        selection.add_argument("--scenario", action="append")
        command.add_argument("--config", type=Path, help="TOML 场景数量配置")
        command.add_argument("--set", action="append", default=[], metavar="SCENE.PARAMETER=VALUE")
        command.add_argument("--workers", type=int, default=1, help="房屋场景并发公司数，1–8")
    resume = commands.add_parser("resume", help="恢复原批次，参数保持不变")
    resume.add_argument("run_id")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "list":
            for name, scenario in REGISTRY.items():
                print(
                    name + "：" + json.dumps(scenario.parameters().model_dump(), ensure_ascii=False)
                )
                print("  依赖：" + ", ".join(scenario.dependencies))
                print("  表：" + ", ".join(sorted(scenario.tables)))
            return 0
        plan = None
        if args.command in {"run", "plan"}:
            plan = resolve_plan(
                list(REGISTRY) if args.all else args.scenario,
                config=args.config,
                overrides=args.set,
                workers=args.workers,
            )
            print(
                json.dumps(
                    {"plan": plan.model_dump(), "estimated": plan.counts()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if args.command == "plan":
                return 0
        if args.command == "coverage":
            database_fingerprint(get_engine(), BACKEND_ROOT)
            print(json.dumps(coverage(get_engine()), ensure_ascii=False, indent=2))
            return 0
        settings = get_settings()
        run(
            plan=plan,
            resume=args.run_id if args.command == "resume" else None,
            root=REPOSITORY_ROOT / ".dev" / "seed",
            backend_root=BACKEND_ROOT,
            factory=get_session_factory(),
            client=get_redis(),
            settings=settings,
            seed=SeedSettings(),
        )
        return 0
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
    except ValidationError as exc:
        fields = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_input=False)
        ]
        print("参数校验失败：" + ", ".join(fields), file=sys.stderr)
    except AppError as exc:
        print(f"业务操作失败：{exc.public_detail or str(exc)}；修正后可续跑该批次", file=sys.stderr)
    except KeyboardInterrupt:
        print("已中断，可使用批次标识续跑", file=sys.stderr)
        return 130
    except Exception as exc:
        # Driver/validation exception messages may contain connection URLs or password inputs.
        print(f"执行失败（{type(exc).__name__}），请检查依赖与本地上下文后续跑", file=sys.stderr)
    finally:
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        if get_redis.cache_info().currsize:
            get_redis().close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
