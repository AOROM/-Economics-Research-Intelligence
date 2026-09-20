"""TLS SMTP delivery with durable acceptance and uncertain-send tracking."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import make_msgid, parseaddr
from pathlib import Path
from typing import Callable

from .state import save_json_atomic


class DeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str
    recipient: str

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        username = os.environ.get("RADAR_SMTP_USERNAME", "").strip()
        password = os.environ.get("RADAR_SMTP_PASSWORD", "")
        sender = os.environ.get("RADAR_MAIL_FROM", username).strip()
        recipient = os.environ.get("RADAR_MAIL_TO", "").strip()
        if not username or not password or not recipient:
            raise DeliveryError("SMTP username, authorization code and recipient must be configured")
        for address in (username, sender, recipient):
            if any(ord(c) < 33 or ord(c) > 126 for c in address) or parseaddr(address)[1] != address or address.count("@") != 1:
                raise DeliveryError("SMTP requires one plain ASCII sender and one recipient address")
        host = os.environ.get("RADAR_SMTP_HOST", "smtp.163.com").strip()
        if not host or any(c in host for c in "/\\\r\n\t @"):
            raise DeliveryError("Invalid SMTP host")
        try:
            port = int(os.environ.get("RADAR_SMTP_PORT", "465"))
        except ValueError as exc:
            raise DeliveryError("Invalid SMTP port") from exc
        if not 1 <= port <= 65535:
            raise DeliveryError("Invalid SMTP port")
        return cls(host, port, username, password, sender, recipient)


def load_deliveries(workdir: Path) -> dict:
    path = workdir / "delivery.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "periods": {}}
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1 or not isinstance(ledger.get("periods"), dict):
        raise DeliveryError("Invalid delivery ledger")
    if any(not isinstance(key, str) or not isinstance(value, dict) for key, value in ledger["periods"].items()):
        raise DeliveryError("Invalid delivery ledger")
    return ledger


def check_period(workdir: Path, period: str) -> str:
    ledger = load_deliveries(workdir)
    if any(row.get("status") in {"transmitting", "uncertain"} for row in ledger["periods"].values()):
        raise DeliveryError("A previous send has an uncertain outcome; verify that message before resending")
    return ledger["periods"].get(period, {}).get("status", "pending")


def resolve_uncertain(workdir: Path, period: str, resolution: str, now: str) -> str:
    """Resolve an uncertain SMTP outcome only after a human checks the mailbox."""
    ledger = load_deliveries(workdir)
    record = ledger["periods"].get(period)
    if not record or record.get("status") not in {"transmitting", "uncertain"}:
        raise DeliveryError("The selected period has no uncertain delivery to resolve")
    if resolution not in {"accepted", "retry"}:
        raise DeliveryError("Resolution must be accepted or retry")
    record["status"] = "accepted" if resolution == "accepted" else "failed"
    record["resolved_at"] = now
    record["resolution"] = "verified_in_mailbox" if resolution == "accepted" else "verified_not_delivered"
    record.pop("error", None)
    save_json_atomic(workdir / "delivery.json", ledger)
    if resolution == "accepted":
        state_path = workdir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.pop("pending_report", None)
        save_json_atomic(state_path, state)
    return record["status"]


def send_report(eml_path: Path, workdir: Path, period: str, settings: SmtpSettings, now: str,
                checkpoint: Callable[[], None] = lambda: None) -> str:
    if check_period(workdir, period) == "accepted":
        return "already_accepted"
    ledger = load_deliveries(workdir)
    message = BytesParser(policy=policy.SMTP).parsebytes(eml_path.read_bytes())
    if message.get_content_type() != "multipart/alternative" or not message.get("Subject"):
        raise DeliveryError("Expected a generated text/HTML email report")
    for header in ("From", "To", "Cc", "Bcc", "Sender", "Return-Path", "Resent-Date", "Resent-From",
                   "Resent-Sender", "Resent-To", "Resent-Cc", "Resent-Bcc", "X-Unsent"):
        if header in message:
            del message[header]
    message["From"] = settings.sender
    message["To"] = settings.recipient
    if not message.get("Message-ID") or str(message["Message-ID"]).endswith("@research-radar.local>"):
        if message.get("Message-ID"):
            del message["Message-ID"]
        message["Message-ID"] = make_msgid(domain=settings.sender.rsplit("@", 1)[1])
    try:
        relative_message = eml_path.resolve().relative_to(workdir.resolve()).as_posix()
    except ValueError as exc:
        raise DeliveryError("Email report must be inside the runtime directory") from exc
    record = {"status": "pending", "message_id": str(message.get("Message-ID", "")),
              "message_file": relative_message,
              "updated_at": now, "recipient": settings.recipient}
    ledger["periods"][period] = record
    client = None
    transmitting = False
    try:
        client = smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, context=ssl.create_default_context())
        client.login(settings.username, settings.password)
        record["status"] = "transmitting"
        save_json_atomic(workdir / "delivery.json", ledger)
        try:
            checkpoint()
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = "State checkpoint failed before transmission"
            save_json_atomic(workdir / "delivery.json", ledger)
            raise DeliveryError(record["error"]) from exc
        transmitting = True
        refused = client.send_message(message, from_addr=settings.sender, to_addrs=[settings.recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as exc:
        record.update(status="failed", error="SMTP rejected authentication, recipient or message")
        save_json_atomic(workdir / "delivery.json", ledger)
        checkpoint()
        raise DeliveryError(record["error"]) from exc
    except (OSError, smtplib.SMTPException) as exc:
        record.update(status="uncertain" if transmitting else "failed",
                      error="SMTP connection ended without confirmed acceptance" if transmitting else "SMTP connection failed before transmission")
        save_json_atomic(workdir / "delivery.json", ledger)
        checkpoint()
        raise DeliveryError(record["error"]) from exc
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                try:
                    client.close()
                except OSError:
                    pass
    # A QUIT failure after send_message succeeded does not undo SMTP acceptance.
    record.update(status="accepted", accepted_at=now)
    record.pop("error", None)
    save_json_atomic(workdir / "delivery.json", ledger)
    state_path = workdir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("pending_report", None)
    save_json_atomic(state_path, state)
    checkpoint()
    return "accepted"
