import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from research_radar.weekly import (STATUS_FILENAME, STATUS_REPOSITORY_PATH, execute,
                                   monday_period, publish_delivery_status, resolve)
from research_radar.paper_table import TABLE_FILENAME


class WeeklyTests(unittest.TestCase):
    def test_period_uses_monday_in_configured_timezone(self):
        self.assertEqual(monday_period(datetime(2026, 9, 27, tzinfo=ZoneInfo("Asia/Shanghai"))), "2026-09-21")

    @patch("research_radar.weekly.SmtpSettings.from_env")
    @patch("research_radar.weekly.publish_delivery_status", return_value="unchanged")
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.check_period", return_value="accepted")
    @patch("research_radar.weekly.run")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai", "monitor_id": "test-monitor"})
    def test_accepted_period_skips_scan_and_resend(self, _config, run, _period, storage_cls,
                                                    publish_status, settings):
        with tempfile.TemporaryDirectory() as temp:
            code, message = execute(Path("config.yaml"), Path(temp), now=datetime(2026, 9, 21, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(code, 0)
        self.assertIn("already accepted", message)
        run.assert_not_called()
        storage_cls.return_value.restore.assert_called_once_with(initialize=False)
        settings.assert_not_called()
        publish_status.assert_called_once_with(Path(temp), "2026-09-21", "test-monitor")

    @patch("research_radar.weekly.GitHubPaperTable")
    @patch("research_radar.weekly.SmtpSettings.from_env", return_value=Mock())
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.check_period", return_value="pending")
    @patch("research_radar.weekly.send_report", return_value="accepted")
    @patch("research_radar.weekly.run")
    @patch("research_radar.weekly.publish_delivery_status", return_value="created")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai", "monitor_id": "test-monitor"})
    def test_partial_coverage_still_delivers_one_consolidated_mail(self, _config, publish_status,
                                                                  run, send, _period, storage_cls,
                                                                  _settings, table_cls):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            digest = root / "digests" / "weekly.md"
            run.return_value = (2, digest)
            table_cls.return_value.publish.return_value = "updated"
            code, message = execute(Path("config.yaml"), root, initialize=True,
                                    now=datetime(2026, 9, 21, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(code, 0)
        self.assertIn("coverage/status code 2", message)
        run.assert_called_once_with(Path("config.yaml"), root, defer_report_ack=True)
        storage_cls.return_value.restore.assert_called_once_with(initialize=True)
        storage_cls.return_value.checkpoint.assert_called_once_with()
        table_cls.return_value.publish.assert_called_once_with(root / TABLE_FILENAME)
        publish_status.assert_called_once_with(root, "2026-09-21", "test-monitor")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], root / "emails" / "weekly.eml")
        self.assertEqual(send.call_args.args[2], "2026-09-21")

    @patch("research_radar.weekly.resolve_uncertain", return_value="accepted")
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.publish_delivery_status", return_value="created")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai", "monitor_id": "test-monitor"})
    def test_manual_resolution_restores_then_checkpoints_encrypted_state(self, _config, publish_status,
                                                                         storage_cls, resolve_delivery):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            message = resolve(Path("config.yaml"), root, "2026-09-21", "accepted",
                              now=datetime(2026, 9, 22, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIn("resolved as accepted", message)
        storage_cls.return_value.restore.assert_called_once_with()
        resolve_delivery.assert_called_once()
        storage_cls.return_value.checkpoint.assert_called_once_with()
        publish_status.assert_called_once_with(root, "2026-09-21", "test-monitor")

    @patch("research_radar.weekly.GitHubPaperTable")
    def test_success_status_is_public_and_secret_free(self, publisher_cls):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "delivery.json").write_text(json.dumps({
                "schema_version": 1,
                "periods": {"2026-09-21": {
                    "status": "accepted",
                    "accepted_at": "2026-09-21T09:12:00+08:00",
                    "recipient": "private@example.com",
                }},
            }), encoding="utf-8")
            publisher_cls.return_value.publish.return_value = "created"
            status = publish_delivery_status(root, "2026-09-21", "test-monitor")
            payload = json.loads((root / STATUS_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(status, "created")
        self.assertEqual(set(payload), {"schema_version", "monitor_id", "period", "status", "accepted_at"})
        self.assertEqual(payload["status"], "accepted")
        publisher_cls.assert_called_once_with(
            path=STATUS_REPOSITORY_PATH,
            commit_message="Record successful weekly monitor run [skip ci]",
        )


if __name__ == "__main__":
    unittest.main()
