import json
import smtplib
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from research_radar.delivery import (DeliveryError, SmtpSettings, check_period,
                                     resolve_uncertain, send_report)
from research_radar.state import save_json_atomic


NOW = "2026-09-21T09:00:00+08:00"
PERIOD = "2026-09-21"


def make_runtime(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    save_json_atomic(root / "state.json", {
        "schema_version": 1, "monitor_id": "test", "works": {},
        "source_scans": {}, "pending_report": [{"work_id": "abc"}],
    })
    message = EmailMessage(policy=policy.SMTP)
    message["Subject"] = "经济学文献简报"
    message["Message-ID"] = "<draft@research-radar.local>"
    message["X-Unsent"] = "1"
    message["Bcc"] = "should-not-survive@example.com"
    message.set_content("纯文本")
    message.add_alternative("<p>HTML</p>", subtype="html")
    eml = root / "emails" / "weekly.eml"
    eml.parent.mkdir()
    eml.write_bytes(message.as_bytes())
    return eml


class FakeSmtp:
    def __init__(self, error=None, quit_error=None):
        self.error = error
        self.quit_error = quit_error
        self.sent = []
        self.logins = []

    def login(self, username, password):
        self.logins.append((username, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.sent.append((message, from_addr, to_addrs))
        if self.error:
            raise self.error
        return {}

    def quit(self):
        if self.quit_error:
            raise self.quit_error

    def close(self):
        pass


class DeliveryTests(unittest.TestCase):
    def settings(self):
        return SmtpSettings("smtp.163.com", 465, "sender@163.com", "secret-code",
                            "sender@163.com", "reader@example.com")

    def test_acceptance_clears_pending_only_after_durable_transmitting_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = make_runtime(root)
            smtp = FakeSmtp(quit_error=smtplib.SMTPServerDisconnected("closed"))
            checkpoints = []

            def checkpoint():
                checkpoints.append(json.loads((root / "delivery.json").read_text(encoding="utf-8"))["periods"][PERIOD]["status"])

            with patch("research_radar.delivery.smtplib.SMTP_SSL", return_value=smtp):
                self.assertEqual(send_report(eml, root, PERIOD, self.settings(), NOW, checkpoint), "accepted")
            self.assertEqual(checkpoints, ["transmitting", "accepted"])
            self.assertNotIn("pending_report", json.loads((root / "state.json").read_text(encoding="utf-8")))
            self.assertEqual(check_period(root, PERIOD), "accepted")
            sent, envelope_from, recipients = smtp.sent[0]
            self.assertEqual(envelope_from, "sender@163.com")
            self.assertEqual(recipients, ["reader@example.com"])
            self.assertEqual(str(sent["To"]), "reader@example.com")
            self.assertIsNone(sent["Bcc"])
            self.assertIsNone(sent["X-Unsent"])
            self.assertTrue(str(sent["Message-ID"]).endswith("@163.com>"))

    def test_explicit_smtp_rejection_is_retryable_and_keeps_pending_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = make_runtime(root)
            smtp = FakeSmtp(smtplib.SMTPDataError(554, b"rejected"))
            with patch("research_radar.delivery.smtplib.SMTP_SSL", return_value=smtp):
                with self.assertRaisesRegex(DeliveryError, r"message content \(code 554\)"):
                    send_report(eml, root, PERIOD, self.settings(), NOW)
            self.assertEqual(check_period(root, PERIOD), "failed")
            self.assertIn("pending_report", json.loads((root / "state.json").read_text(encoding="utf-8")))

    def test_smtp_rejection_diagnostics_hide_addresses_and_server_text(self):
        cases = [
            (smtplib.SMTPAuthenticationError(535, b"bad secret"), "authentication (code 535)"),
            (smtplib.SMTPSenderRefused(553, b"bad sender", "private@163.com"), "sender (code 553)"),
            (smtplib.SMTPRecipientsRefused({"private@example.com": (550, b"bad recipient")}),
             "recipient (code 550)"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                eml = make_runtime(root)
                smtp = FakeSmtp(error)
                with patch("research_radar.delivery.smtplib.SMTP_SSL", return_value=smtp):
                    with self.assertRaisesRegex(DeliveryError, expected.replace("(", r"\(").replace(")", r"\)")) as raised:
                        send_report(eml, root, PERIOD, self.settings(), NOW)
                public_error = str(raised.exception)
                self.assertNotIn("private", public_error)
                self.assertNotIn("secret", public_error)

    def test_disconnect_during_send_blocks_automatic_resend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = make_runtime(root)
            smtp = FakeSmtp(smtplib.SMTPServerDisconnected("outcome unknown"))
            with patch("research_radar.delivery.smtplib.SMTP_SSL", return_value=smtp):
                with self.assertRaises(DeliveryError):
                    send_report(eml, root, PERIOD, self.settings(), NOW)
            with self.assertRaisesRegex(DeliveryError, "uncertain outcome"):
                check_period(root, "2026-09-28")
            self.assertIn("pending_report", json.loads((root / "state.json").read_text(encoding="utf-8")))

    def test_failed_presend_checkpoint_prevents_transmission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            eml = make_runtime(root)
            smtp = FakeSmtp()
            with patch("research_radar.delivery.smtplib.SMTP_SSL", return_value=smtp):
                with self.assertRaisesRegex(DeliveryError, "checkpoint failed"):
                    send_report(eml, root, PERIOD, self.settings(), NOW,
                                lambda: (_ for _ in ()).throw(OSError("storage unavailable")))
            self.assertEqual(smtp.sent, [])

    def test_human_resolution_clears_or_preserves_pending_as_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_runtime(root)
            save_json_atomic(root / "delivery.json", {"schema_version": 1, "periods": {
                PERIOD: {"status": "uncertain", "message_id": "<one@163.com>"}
            }})
            self.assertEqual(resolve_uncertain(root, PERIOD, "retry", NOW), "failed")
            self.assertIn("pending_report", json.loads((root / "state.json").read_text(encoding="utf-8")))
            ledger = json.loads((root / "delivery.json").read_text(encoding="utf-8"))
            ledger["periods"][PERIOD]["status"] = "uncertain"
            save_json_atomic(root / "delivery.json", ledger)
            self.assertEqual(resolve_uncertain(root, PERIOD, "accepted", NOW), "accepted")
            self.assertNotIn("pending_report", json.loads((root / "state.json").read_text(encoding="utf-8")))

    def test_environment_validation_and_repr_do_not_expose_password(self):
        env = {"RADAR_SMTP_USERNAME": "sender@163.com", "RADAR_SMTP_PASSWORD": "secret-code",
               "RADAR_MAIL_TO": "reader@example.com"}
        with patch.dict("os.environ", env, clear=True):
            settings = SmtpSettings.from_env()
        self.assertNotIn("secret-code", repr(settings))
        with patch.dict("os.environ", {**env, "RADAR_MAIL_TO": "reader@example.com\nBcc:x@example.com"}, clear=True):
            with self.assertRaises(DeliveryError):
                SmtpSettings.from_env()


if __name__ == "__main__":
    unittest.main()
