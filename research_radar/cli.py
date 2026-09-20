"""Run one monitoring cycle. Scheduling belongs to the host or cron."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import load_config
from .digest import render_digest
from .documents import import_fulltext
from .mail import render_mail, write_mail
from .sources import ChineseOfficialSource, InternationalFeedSource, SourceError
from .state import apply_observations, load_state, research_map, save_json_atomic
from .summaries import refresh_summaries


def _restore_pending(state: dict, changes: dict) -> None:
    for saved in state.get("pending_report", []):
        work = state["works"].get(saved["work_id"])
        if not work:
            continue
        kind = saved["change_type"]
        bucket = changes.setdefault(kind, [])
        if any(row["work_id"] == saved["work_id"] and row["event"]["fingerprint"] == saved["fingerprint"] for row in bucket):
            continue
        event = next((v for v in work["versions"] if v["fingerprint"] == saved["fingerprint"]), work["versions"][-1])
        bucket.append({"work_id": saved["work_id"], "work": work, "event": event, "change_type": kind})


def _save_pending(state: dict, changes: dict) -> None:
    state["pending_report"] = [
        {"work_id": row["work_id"], "fingerprint": row["event"]["fingerprint"], "change_type": kind}
        for kind, rows in changes.items() if kind != "possible_links" for row in rows
    ]


def run(config_path: Path, workdir: Path, *, summaries_only: bool = False, retry_summaries: bool = False,
        fulltext: Path | None = None, work_id: str | None = None, fulltext_source: str | None = None,
        defer_report_ack: bool = False) -> tuple[int, Path]:
    """Run one cycle; retain the legacy (code, Markdown path) Python API.

    The CLI prints the .eml draft by default. All formats share one stem.
    """
    config = load_config(config_path)
    now = datetime.now(ZoneInfo(config.get("timezone", "Asia/Shanghai"))).isoformat(timespec="seconds")
    state_path = workdir / "state.json"
    previous = load_state(state_path, config["monitor_id"])
    if fulltext:
        if work_id not in previous["works"]:
            raise ValueError("Full text import requires an existing --work-id")
        import_fulltext(fulltext, previous["works"][work_id], workdir, fulltext_source)
        summaries_only = True
    sources = [ChineseOfficialSource(j) for j in config["chinese_monitor"]["journals"] if j.get("status", "active") == "active"]
    sources.extend(InternationalFeedSource(s) for s in config.get("international_monitor", {}).get("sources", []))
    if not sources and not summaries_only:
        raise ValueError("Configure at least one Chinese journal or international source")
    scans, failures = [], []
    for source in ([] if summaries_only else sources):
        try:
            scans.append(source.scan(now))
        except Exception as exc:
            failures.append({"source_id": source.source_id, "source_name": getattr(source, "journal", {}).get("name") or getattr(source, "source", {}).get("name"), "error": str(exc)})
    updated, changes = apply_observations(previous, scans, config["topic"], now)
    _restore_pending(updated, changes)
    _save_pending(updated, changes)
    # Keep discoveries/report events before any model call. Summaries can be
    # retried and a failed export must not swallow a new-paper notification.
    save_json_atomic(state_path, updated)
    summary_result = refresh_summaries(updated, config, workdir, now, retry=retry_summaries)
    changed_ids = list(updated["works"]) if summaries_only else summary_result["changed"]
    changes["summary_updated"] = [
        {"work_id": wid, "work": updated["works"][wid], "event": updated["works"][wid]["versions"][-1], "change_type": "summary_updated"}
        for wid in changed_ids
    ] + changes.get("summary_updated", [])
    _save_pending(updated, changes)
    save_json_atomic(state_path, updated)
    digest = render_digest(config, changes, scans, failures, now, previous)
    stem = now[:10] + "-" + now[11:19].replace(":", "") + "-" + uuid4().hex[:6]
    destination = workdir / "digests" / (stem + ".md")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    temp.write_text(digest, encoding="utf-8")
    temp.replace(destination)
    report = render_mail(config, updated, changes, scans, failures, now, summary_result, summaries_only=summaries_only)
    write_mail(report, workdir / "emails", stem, config, now)
    save_json_atomic(workdir / "research_map.json", research_map(updated))
    # Interactive runs acknowledge the report after all local files exist. A
    # delivery runner defers acknowledgement until its SMTP server accepts it.
    if not defer_report_ack:
        updated.pop("pending_report", None)
    save_json_atomic(state_path, updated)
    incomplete = summary_result["pending"] + summary_result["failed"] + summary_result["awaiting_configuration"]
    code = (4 if incomplete else 0) if summaries_only or (scans and not failures) else (2 if scans else 1)
    return code, destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one economics research monitoring cycle")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--format", choices=["email", "html", "text", "markdown"], default="email", help="Primary output path (all formats are saved)")
    parser.add_argument("--summaries-only", action="store_true", help="Summarize/export saved papers without scanning websites")
    parser.add_argument("--retry-summaries", action="store_true", help="Reset attempts for unfinished model summaries")
    parser.add_argument("--import-fulltext", type=Path, help="Import a user-provided .txt/.md/.pdf for an existing paper")
    parser.add_argument("--work-id", help="ResearchWork identifier for full text import")
    parser.add_argument("--fulltext-source", help="Source URL for imported text; defaults to the paper's official URL")
    args = parser.parse_args(argv)
    try:
        code, digest_path = run(args.config, args.workdir, summaries_only=args.summaries_only,
                                retry_summaries=args.retry_summaries, fulltext=args.import_fulltext,
                                work_id=args.work_id, fulltext_source=args.fulltext_source)
    except (OSError, ValueError) as exc:
        print(f"Configuration/state error: {exc}", file=sys.stderr)
        return 3
    output = digest_path if args.format == "markdown" else args.workdir / "emails" / (digest_path.stem + "." + {"email": "eml", "html": "html", "text": "txt"}[args.format])
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
