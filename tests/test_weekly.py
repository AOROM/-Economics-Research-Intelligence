import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from research_radar.weekly import execute, monday_period, resolve


class WeeklyTests(unittest.TestCase):
    def test_period_uses_monday_in_configured_timezone(self):
        self.assertEqual(monday_period(datetime(2026, 9, 27, tzinfo=ZoneInfo("Asia/Shanghai"))), "2026-09-21")

    @patch("research_radar.weekly.SmtpSettings.from_env")
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.check_period", return_value="accepted")
    @patch("research_radar.weekly.run")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai"})
    def test_accepted_period_skips_scan_and_resend(self, _config, run, _period, storage_cls, _settings):
        with tempfile.TemporaryDirectory() as temp:
            code, message = execute(Path("config.yaml"), Path(temp), now=datetime(2026, 9, 21, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(code, 0)
        self.assertIn("already accepted", message)
        run.assert_not_called()
        storage_cls.return_value.restore.assert_called_once_with(initialize=False)

    @patch("research_radar.weekly.SmtpSettings.from_env", return_value=Mock())
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.check_period", return_value="pending")
    @patch("research_radar.weekly.send_report", return_value="accepted")
    @patch("research_radar.weekly.run")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai"})
    def test_partial_coverage_still_delivers_one_consolidated_mail(self, _config, run, send, _period,
                                                                  storage_cls, _settings):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            digest = root / "digests" / "weekly.md"
            run.return_value = (2, digest)
            code, message = execute(Path("config.yaml"), root, initialize=True,
                                    now=datetime(2026, 9, 21, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertEqual(code, 0)
        self.assertIn("coverage/status code 2", message)
        run.assert_called_once_with(Path("config.yaml"), root, defer_report_ack=True)
        storage_cls.return_value.restore.assert_called_once_with(initialize=True)
        storage_cls.return_value.checkpoint.assert_called_once_with()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], root / "emails" / "weekly.eml")
        self.assertEqual(send.call_args.args[2], "2026-09-21")

    @patch("research_radar.weekly.resolve_uncertain", return_value="accepted")
    @patch("research_radar.weekly.GitHubState")
    @patch("research_radar.weekly.load_config", return_value={"timezone": "Asia/Shanghai"})
    def test_manual_resolution_restores_then_checkpoints_encrypted_state(self, _config, storage_cls, resolve_delivery):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            message = resolve(Path("config.yaml"), root, "2026-09-21", "accepted",
                              now=datetime(2026, 9, 22, 9, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIn("resolved as accepted", message)
        storage_cls.return_value.restore.assert_called_once_with()
        resolve_delivery.assert_called_once()
        storage_cls.return_value.checkpoint.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
