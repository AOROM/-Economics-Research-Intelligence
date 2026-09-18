import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_radar.cli import run
from research_radar.config import load_config
from research_radar.sources import ScanResult, SourceError


CONFIG = """monitor_id: test
timezone: Asia/Shanghai
topic: {statement: 企业边界}
chinese_monitor:
  official_site_only: true
  auto_expand_journals: false
  allow_database_discovery: false
  journals:
    - name: 测试期刊
      homepage: https://journal.example/
      priority: critical
      surfaces:
        - label: 网络首发
          url: https://journal.example/online
          item_selector: .paper
          title_selector: .title
          link_selector: a
international_monitor:
  sources:
    - {provider: cepr, name: CEPR, feed_url: https://cepr.org/rss/discussion-paper}
"""


class CliTests(unittest.TestCase):
    def test_user_journal_whitelist_has_explicit_pending_coverage(self):
        preset = Path(__file__).parent.parent / "presets" / "corporate-finance-firm-boundaries.yaml"
        journals = load_config(preset)["chinese_monitor"]["journals"]
        self.assertEqual(len(journals), 11)
        self.assertEqual(sum(j.get("status") == "active" for j in journals), 3)
        self.assertEqual(sum(j.get("status") == "pending" for j in journals), 8)

    def test_pending_journal_is_reported_without_scanning(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text("""monitor_id: test
topic: {statement: 企业边界}
chinese_monitor:
  official_site_only: true
  auto_expand_journals: false
  allow_database_discovery: false
  journals:
    - {name: 待接入期刊, homepage: 'http://journal.example/', status: pending, priority: critical}
international_monitor:
  sources:
    - {provider: cepr, name: CEPR, feed_url: 'https://cepr.org/rss/discussion-paper'}
""", encoding="utf-8")
            with patch("research_radar.cli.InternationalFeedSource.scan", return_value=ScanResult("cepr:CEPR", "CEPR", "working_paper", [], 1, "feed-snapshot")), patch("research_radar.cli.ChineseOfficialSource.scan") as scan:
                code, digest = run(config, Path(temp) / "monitor")
            self.assertEqual(code, 0)
            scan.assert_not_called()
            self.assertIn("待接入，尚未扫描", digest.read_text(encoding="utf-8"))

    def test_partial_run_preserves_failed_source_and_marks_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text(CONFIG, encoding="utf-8")
            workdir = Path(temp) / "monitor"
            chinese = ScanResult("zh:测试期刊", "测试期刊", "chinese_journal", [], 1, "official-surface")
            with patch("research_radar.cli.ChineseOfficialSource.scan", return_value=chinese), patch("research_radar.cli.InternationalFeedSource.scan", side_effect=SourceError("blocked")):
                code, digest = run(config, workdir)
            self.assertEqual(code, 2)
            report = digest.read_text(encoding="utf-8")
            self.assertIn("覆盖不完整", report)
            self.assertIn("CEPR", report)
            state = (workdir / "state.json").read_text(encoding="utf-8")
            self.assertIn("zh:测试期刊", state)
            self.assertNotIn('"cepr:CEPR"', state)


if __name__ == "__main__":
    unittest.main()
