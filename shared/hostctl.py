#!/usr/bin/env python3
"""
Shared host-side instance discovery for Game Commander.

This is the first v3.0 refactor brick:
- keep shell entrypoints
- move instance discovery/resolution into Python
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import instanceenv

DEFAULT_SEARCH_ROOTS = ("/home", "/opt", "/root")
DEFAULT_MAX_DEPTH = 5


def parse_env_file(path: str | Path) -> dict[str, str]:
    return instanceenv.parse_env_file(path)


def _walk_candidate_files(root: str | Path, max_depth: int = DEFAULT_MAX_DEPTH):
    root_path = Path(root)
    if not root_path.exists():
        return
    base_depth = len(root_path.parts)
    for current_root, dirs, files in os.walk(root_path):
        current_path = Path(current_root)
        depth = len(current_path.parts) - base_depth
        if depth >= max_depth:
            dirs[:] = []
        if "deploy_config.env" in files:
            yield current_path / "deploy_config.env"


def discover_instance_configs(
    search_roots: list[str] | tuple[str, ...] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[Path]:
    roots = tuple(search_roots or DEFAULT_SEARCH_ROOTS)
    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for candidate in _walk_candidate_files(root, max_depth=max_depth):
            candidate = candidate.resolve()
            if candidate in seen:
                continue
            env = parse_env_file(candidate)
            if not env.get("GAME_ID"):
                continue
            seen.add(candidate)
            found.append(candidate)
    return sorted(found, key=lambda item: str(item))


def discover_instance_records(
    search_roots: list[str] | tuple[str, ...] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for cfg in discover_instance_configs(search_roots=search_roots, max_depth=max_depth):
        records.append(instanceenv.load_instance_record(cfg))
    return records


def resolve_instance_config(
    instance_name: str,
    search_roots: list[str] | tuple[str, ...] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Path | None:
    for record in discover_instance_records(search_roots=search_roots, max_depth=max_depth):
        if record.get("instance_id") == instance_name:
            return Path(record["config"])
    return None


def _cmd_list_configs(args: argparse.Namespace) -> int:
    configs = discover_instance_configs(search_roots=args.root, max_depth=args.max_depth)
    if args.json:
        print(json.dumps([str(path) for path in configs], ensure_ascii=True))
    else:
        for path in configs:
            print(path)
    return 0


def _cmd_list_instances(args: argparse.Namespace) -> int:
    records = discover_instance_records(search_roots=args.root, max_depth=args.max_depth)
    if args.json:
        print(json.dumps(records, ensure_ascii=True))
        return 0
    for item in records:
        print(f"{item['instance_id']} {item['game_id']} {item['config']}")
    return 0


def _cmd_resolve_config(args: argparse.Namespace) -> int:
    path = resolve_instance_config(args.instance, search_roots=args.root, max_depth=args.max_depth)
    if not path:
        return 1
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game Commander host instance helper")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common_flags(cmd):
        cmd.add_argument("--root", action="append", default=[], help="Search root override")
        cmd.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)

    list_configs = sub.add_parser("list-configs")
    add_common_flags(list_configs)
    list_configs.add_argument("--json", action="store_true")
    list_configs.set_defaults(func=_cmd_list_configs)

    list_instances = sub.add_parser("list-instances")
    add_common_flags(list_instances)
    list_instances.add_argument("--json", action="store_true")
    list_instances.set_defaults(func=_cmd_list_instances)

    resolve_config = sub.add_parser("resolve-config")
    add_common_flags(resolve_config)
    resolve_config.add_argument("--instance", required=True)
    resolve_config.set_defaults(func=_cmd_resolve_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.root:
        args.root = list(DEFAULT_SEARCH_ROOTS)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
