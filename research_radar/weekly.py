"""Run one encrypted, idempotent weekly scan and deliver one email."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cli import run
from .cloud_state import CloudStateError, GitHubState
from .config import load_config
from .delivery import (DeliveryError, SmtpSettings, check_period,
                       resolve_uncertain, send_report)
from .paper_table import GitHubPaperTable, PaperTableError, TABLE_FILENAME


def monday_period(now: datetime) -> str:
    return (now.date() - timedelta(days=now.weekday())).isoformat()


def execute(config_path: Path, workdir: Path, *, initialize: bool = False,
            now: datetime | None = None) -> tuple[int, str]:
    """Restore state, scan once, checkpoint it, then deliver exactly one report period."""
    config = load_config(config_path)
    zone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    current = now.astimezone(zone) if now else datetime.now(zone)
    period = monday_period(current)
    settings = SmtpSettings.from_env()
    storage = GitHubState(workdir)
    storage.restore(initialize=initialize)
    if check_period(workdir, period) == "accepted":
        return 0, f"Weekly report for {period} was already accepted; no scan or resend was performed."

    try:
        scan_code, digest_path = run(config_path, workdir, defer_report_ack=True)
    except Exception as exc:
        # A scan can persist discoveries before a later processing error. Keep
        # that state when possible so the next run can resume without loss.
        if (workdir / "state.json").exists():
            try:
                storage.checkpoint()
            except Exception as checkpoint_exc:
                raise CloudStateError("Monitoring failed and its latest state could not be checkpointed") from checkpoint_exc
        raise RuntimeError("Monitoring failed before a report could be delivered") from exc

    storage.checkpoint()
    table_status = GitHubPaperTable().publish(workdir / TABLE_FILENAME)
    eml_path = workdir / "emails" / (digest_path.stem + ".eml")
    status = send_report(eml_path, workdir, period, settings,
                         current.isoformat(timespec="seconds"), storage.checkpoint)
    if scan_code:
        return 0, (f"Email {status} for {period}; monitoring completed with coverage/status code {scan_code}; "
                   f"cumulative paper table {table_status}.")
    return 0, f"Email {status} for {period}; monitoring and delivery completed; cumulative paper table {table_status}."


def resolve(config_path: Path, workdir: Path, period: str, resolution: str,
            *, now: datetime | None = None) -> str:
    config = load_config(config_path)
    zone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    current = now.astimezone(zone) if now else datetime.now(zone)
    storage = GitHubState(workdir)
    storage.restore()
    status = resolve_uncertain(workdir, period, resolution, current.isoformat(timespec="seconds"))
    storage.checkpoint()
    return f"Delivery for {period} was resolved as {status}."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run and email one weekly economics literature report")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true",
                        help="Allow creation of the encrypted state branch on the first run")
    parser.add_argument("--resolve-period", help="Monday date of an uncertain delivery, YYYY-MM-DD")
    parser.add_argument("--resolution", choices=["accepted", "retry"],
                        help="Outcome verified by checking the destination mailbox")
    args = parser.parse_args(argv)
    if bool(args.resolve_period) != bool(args.resolution):
        parser.error("--resolve-period and --resolution must be used together")
    if args.resolve_period and args.initialize:
        parser.error("--initialize cannot be combined with delivery resolution")
    try:
        if args.resolve_period:
            message = resolve(args.config, args.workdir, args.resolve_period, args.resolution)
            code = 0
        else:
            code, message = execute(args.config, args.workdir, initialize=args.initialize)
    except DeliveryError as exc:
        print("Weekly email delivery stopped: " + str(exc), file=sys.stderr)
        return 5
    except CloudStateError as exc:
        print("Encrypted state storage stopped: " + str(exc), file=sys.stderr)
        return 6
    except PaperTableError as exc:
        print("Cumulative paper table stopped: " + str(exc), file=sys.stderr)
        return 7
    except (OSError, RuntimeError, ValueError) as exc:
        print("Weekly monitoring stopped: " + str(exc), file=sys.stderr)
        return 3
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
