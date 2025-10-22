#!/usr/bin/env python3
"""Storage retention enforcement for Oddcrawler."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, MutableMapping, Optional

import yaml

DEFAULT_STORAGE_CONFIG = Path("config/storage.yaml")
TARGET_SECTIONS = ("raw_html", "excerpts", "vectors", "graphs", "dangerous_breadcrumbs")


@dataclass
class PurgeResult:
    section: str
    path: Path
    removed: List[Path]
    skipped_reason: Optional[str] = None


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load the storage configuration YAML."""
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise SystemExit(f"Storage config not found: {config_path}") from exc


def resolve_base_dir(config_path: Path, config: MutableMapping[str, Any]) -> Path:
    base_dir = config.get("base_dir", "var/oddcrawler")
    base_path = Path(base_dir)
    if not base_path.is_absolute():
        base_path = (config_path.parent / base_path).resolve()
    return base_path


def resolve_section_path(section: str, base_dir: Path, policy: MutableMapping[str, Any]) -> Path:
    raw_path = policy.get("path") or section
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path
    return path


def find_expired_files(path: Path, ttl_days: Optional[int]) -> Iterable[Path]:
    if ttl_days is None:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            yield file_path


def remove_files(files: Iterable[Path]) -> List[Path]:
    removed: List[Path] = []
    for file_path in files:
        try:
            file_path.unlink(missing_ok=True)
            removed.append(file_path)
        except OSError:
            continue
    return removed


def purge_storage(config_path: Path, dry_run: bool) -> List[PurgeResult]:
    config = load_config(config_path)
    base_dir = resolve_base_dir(config_path, config)
    results: List[PurgeResult] = []

    for section in TARGET_SECTIONS:
        policy = config.get(section, {})
        if not policy.get("enabled", False):
            results.append(PurgeResult(section=section, path=base_dir, removed=[], skipped_reason="disabled"))
            continue

        ttl_days = policy.get("ttl_days")
        if ttl_days is None:
            results.append(PurgeResult(section=section, path=base_dir, removed=[], skipped_reason="ttl_unset"))
            continue

        section_path = resolve_section_path(section, base_dir, policy)
        if not section_path.exists():
            results.append(PurgeResult(section=section, path=section_path, removed=[], skipped_reason="missing"))
            continue

        expired_files = list(find_expired_files(section_path, ttl_days))
        if dry_run:
            results.append(PurgeResult(section=section, path=section_path, removed=expired_files))
            continue

        removed = remove_files(expired_files)
        results.append(PurgeResult(section=section, path=section_path, removed=removed))

    return results


def format_summary(results: List[PurgeResult], dry_run: bool) -> str:
    lines = ["Oddcrawler storage purge" + (" (dry-run)" if dry_run else "")]
    for result in results:
        if result.skipped_reason == "disabled":
            lines.append(f"- {result.section}: disabled in config")
        elif result.skipped_reason == "ttl_unset":
            lines.append(f"- {result.section}: ttl_days not set; skipping")
        elif result.skipped_reason == "missing":
            lines.append(f"- {result.section}: path {result.path} not found; skipping")
        else:
            count = len(result.removed)
            action = "would be purged" if dry_run else "purged"
            lines.append(f"- {result.section}: {count} file(s) {action} from {result.path}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce Oddcrawler storage retention policies.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_STORAGE_CONFIG,
        help="Path to storage configuration YAML (default: config/storage.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be purged without deleting anything.",
    )
    args = parser.parse_args()

    results = purge_storage(args.config, args.dry_run)
    print(format_summary(results, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
