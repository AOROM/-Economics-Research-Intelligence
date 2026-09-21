import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_radar.cli import _restore_pending, run
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
    def test_scheduled_preset_contains_eleven_chinese_and_eight_english_top_journals(self):
        preset = Path(__file__).parent.parent / "presets" / "corporate-finance-firm-boundaries.yaml"
        loaded = load_config(preset)
        journals = loaded["chinese_monitor"]["journals"]
        self.assertEqual(len(journals), 11)
        self.assertEqual(sum(j.get("status") == "active" for j in journals), 10)
        self.assertEqual(sum(j.get("status") == "blocked" for j in journals), 1)
        self.assertEqual(
            [journal["name"] for journal in journals],
            ["经济研究", "管理世界", "经济学（季刊）", "世界经济", "中国工业经济", "金融研究",
             "财贸经济", "数量经济技术经济研究", "经济学动态", "经济理论与经济管理", "财经研究"],
        )
        english = loaded["international_monitor"]["sources"]
        self.assertEqual(len(english), 8)
        self.assertEqual(sum(source["tier"] == "TOP" for source in english), 8)
        self.assertEqual(sum(source["tier"] == "一级A" for source in english), 0)
        self.assertEqual(len({source["issn"] for source in english}), 8)
        self.assertEqual(english[0]["name"], "American Economic Review")
        self.assertEqual(english[-1]["name"], "Review of Financial Studies")

    def test_pending_items_from_removed_sources_are_not_restored(self):
        removed = {
            "source_id": "zh:已移除期刊",
            "source_name": "已移除期刊",
            "fingerprint": "old-version",
        }
        state = {
            "works": {"work-1": {"versions": [removed]}},
            "pending_report": [{
                "work_id": "work-1",
                "fingerprint": "old-version",
                "change_type": "new",
            }],
        }
        config = {
            "chinese_monitor": {"journals": []},
            "international_monitor": {"sources": [{
                "id": "crossref:0002-8282",
                "provider": "crossref",
                "name": "American Economic Review",
            }]},
        }
        changes = {}
        _restore_pending(state, changes, config)
        self.assertEqual(changes, {"new": []})

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
    - {name: 官网阻塞期刊, homepage: 'http://blocked.example/', status: blocked, priority: critical, note: 官网持续超时}
international_monitor:
  sources:
    - {provider: cepr, name: CEPR, feed_url: 'https://cepr.org/rss/discussion-paper'}
""", encoding="utf-8")
            with patch("research_radar.cli.InternationalFeedSource.scan", return_value=ScanResult("cepr:CEPR", "CEPR", "working_paper", [], 1, "feed-snapshot")), patch("research_radar.cli.ChineseOfficialSource.scan") as scan:
                code, digest = run(config, Path(temp) / "monitor")
            self.assertEqual(code, 0)
            scan.assert_not_called()
            self.assertIn("待接入，尚未扫描", digest.read_text(encoding="utf-8"))
            self.assertIn("官网外部阻塞，尚未扫描", digest.read_text(encoding="utf-8"))

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

