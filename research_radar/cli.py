"""Run one monitoring cycle. Scheduling belongs to the host or cron."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .digest import render_digest
from .sources import ChineseOfficialSource, InternationalFeedSource, SourceError
from .state import apply_observations, load_state, research_map, save_json_atomic


def run(config_path: Path, workdir: Path) -> tuple[int, Path]:
    config = load_config(config_path)
    now = datetime.now(ZoneInfo(config.get("timezone", "Asia/Shanghai"))).isoformat(timespec="seconds")
    state_path = workdir / "state.json"
    previous = load_state(state_path, config["monitor_id"])
    sources = [ChineseOfficialSource(j) for j in config["chinese_monitor"]["journals"]]
    sources.extend(InternationalFeedSource(s) for s in config.get("international_monitor", {}).get("sources", []))
    if not sources:
        raise ValueError("Configure at least one Chinese journal or international source")
    scans, failures = [], []
    for source in sources:
        try:
            scans.append(source.scan(now))
        except Exception as exc:
            failures.append({"source_id": source.source_id, "source_name": getattr(source, "journal", {}).get("name") or getattr(source, "source", {}).get("name"), "error": str(exc)})
    updated, changes = apply_observations(previous, scans, config["topic"], now)
    digest = render_digest(config, changes, scans, failures, now, previous)
    destination = workdir / "digests" / (now[:10] + "-" + now[11:19].replace(":", "") + ".md")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_text(digest, encoding="utf-8")
    temp.replace(destination)
    if scans:
        save_json_atomic(state_path, updated)
        save_json_atomic(workdir / "research_map.json", research_map(updated))
    return (0 if scans and not failures else 2 if scans else 1), destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one economics research monitoring cycle")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        code, digest_path = run(args.config, args.workdir)
    except (OSError, ValueError) as exc:
        print(f"Configuration/state error: {exc}", file=sys.stderr)
        return 3
    print(digest_path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
