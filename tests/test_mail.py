import json
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from research_radar.cli import run
from research_radar.mail import render_mail, write_mail
from research_radar.sources import ScanResult
from research_radar.state import apply_observations, empty_state, save_json_atomic
from research_radar.summaries import refresh_summaries
from test_cli import CONFIG
from test_state import observation, scan
from test_summaries import NOW, TOPIC, prepared


def mail_config():
    return {"topic": TOPIC, "chinese_monitor": {"journals": [{"name": "测试期刊", "priority": "critical"}]}}


class MailTests(unittest.TestCase):
    def test_utf8_subject_plain_and_html_mime_parts_roundtrip(self):
        state, _, changes = prepared()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            config = mail_config()
            result = refresh_summaries(state, config, path, NOW)
            report = render_mail(config, state, changes, [scan(observation())], [], NOW, result)
            outputs = write_mail(report, path / "emails", "test", config, NOW)
            message = BytesParser(policy=policy.default).parsebytes(outputs["eml"].read_bytes())
            self.assertEqual(str(message["Subject"]), report.subject)
            self.assertIsNone(message["To"])
            self.assertEqual(message["X-Unsent"], "1")
            self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().replace("\r\n", "\n").strip(), report.text.strip())
            self.assertIn("企业纵向一体化与融资约束", message.get_body(preferencelist=("html",)).get_content())
            self.assertIn("首次基线收录 1 篇", report.text)
            self.assertIn("新增 0 篇", report.subject)
            self.assertEqual({p.suffix for p in outputs.values()}, {".txt", ".html", ".eml"})

    def test_html_escapes_source_content_and_rejects_unsafe_links(self):
        state, work, changes = prepared()
        work["versions"][-1]["title"] = '<script>alert("bad")</script>论文标题'
        work["versions"][-1]["official_url"] = 'javascript:alert("bad")'
        report = render_mail(mail_config(), state, changes, [], [], NOW, {})
        self.assertNotIn("<script>", report.html)
        self.assertNotIn('href="javascript:', report.html)
        self.assertIn("&lt;script&gt;", report.html)

    def test_low_relevance_chinese_papers_and_partial_coverage_are_visible(self):
        state, changes = apply_observations(empty_state("test"), [scan()], TOPIC, NOW)
        item = observation(title="城市就业与工资变化", doi="10.1234/low")
        item["abstract"] = "本文研究城市就业。"
        state, changes = apply_observations(state, [scan(item)], TOPIC, NOW)
        with tempfile.TemporaryDirectory() as temp:
            result = refresh_summaries(state, mail_config(), Path(temp), NOW)
        report = render_mail(mail_config(), state, changes, [scan(item)], [{"source_name": "故障期刊", "error": "HTTP 502"}], NOW, result)
        self.assertIn("中文期刊其他更新", report.text)
        self.assertIn("城市就业与工资变化", report.text)
        self.assertIn("故障期刊：覆盖不完整", report.text)
        self.assertIn("部分来源未完成", report.subject)

    def test_same_paper_appears_once_when_summary_and_publication_both_change(self):
        state, work, changes = prepared()
        changes["summary_updated"] = [{"work_id": work["canonical_work_id"], "work": work, "event": work["versions"][-1], "change_type": "summary_updated"}]
        report = render_mail(mail_config(), state, changes, [], [], NOW, {})
        self.assertEqual(report.text.count("\n" + work["title"] + "\n"), 1)

    def test_previous_versions_summary_is_not_used_for_current_version(self):
        state, work, changes = prepared()
        work["summary"] = {"version_fingerprint": "old", "claims": [{"text": "旧版本的主要结果"}]}
        report = render_mail(mail_config(), state, changes, [], [], NOW, {})
        self.assertNotIn("旧版本的主要结果", report.text)


class MailIntegrationTests(unittest.TestCase):
    def test_summaries_only_generates_mail_without_network_or_new_publications(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.yaml"
            config.write_text(CONFIG, encoding="utf-8")
            state, _, _ = prepared()
            workdir = root / "monitor"
            save_json_atomic(workdir / "state.json", state)
            with patch("research_radar.cli.ChineseOfficialSource.scan") as chinese, patch("research_radar.cli.InternationalFeedSource.scan") as international:
                code, digest = run(config, workdir, summaries_only=True)
            self.assertEqual(code, 0)
            chinese.assert_not_called()
            international.assert_not_called()
            text = (workdir / "emails" / (digest.stem + ".txt")).read_text(encoding="utf-8")
            self.assertIn("未重新扫描期刊", text)
            self.assertIn("融资成本降低2个百分点", text)
            self.assertIn("新增论文 0 篇", text)
            self.assertEqual(len(next(iter(json.loads((workdir / "state.json").read_text(encoding="utf-8"))["works"].values()))["versions"]), 1)

    def test_failed_email_export_keeps_new_paper_notification_for_next_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.yaml"
            config.write_text(CONFIG, encoding="utf-8")
            workdir = root / "monitor"
            state, _ = apply_observations(empty_state("test"), [scan()], TOPIC, NOW)
            save_json_atomic(workdir / "state.json", state)
            with patch("research_radar.cli.ChineseOfficialSource.scan", return_value=scan(observation())), patch("research_radar.cli.InternationalFeedSource.scan", return_value=ScanResult("cepr:CEPR", "CEPR", "working_paper", [], 1, "feed-snapshot")):
                with patch("research_radar.cli.write_mail", side_effect=OSError("disk unavailable")):
                    with self.assertRaises(OSError):
                        run(config, workdir)
                saved = json.loads((workdir / "state.json").read_text(encoding="utf-8"))
                self.assertTrue(saved["pending_report"])
                code, digest = run(config, workdir)
            self.assertEqual(code, 0)
            text = (workdir / "emails" / (digest.stem + ".txt")).read_text(encoding="utf-8")
            self.assertIn("新增论文 1 篇", text)
            saved = json.loads((workdir / "state.json").read_text(encoding="utf-8"))
            self.assertNotIn("pending_report", saved)

    def test_delivery_run_defers_pending_acknowledgement_until_smtp_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.yaml"
            config.write_text(CONFIG, encoding="utf-8")
            workdir = root / "monitor"
            with patch("research_radar.cli.ChineseOfficialSource.scan", return_value=scan(observation())), patch("research_radar.cli.InternationalFeedSource.scan", return_value=ScanResult("cepr:CEPR", "CEPR", "working_paper", [], 1, "feed-snapshot")):
                code, _ = run(config, workdir, defer_report_ack=True)
            self.assertEqual(code, 0)
            saved = json.loads((workdir / "state.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["pending_report"])

    def test_unconfigured_model_reports_partial_summary_without_losing_discoveries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.yaml"
            config.write_text(CONFIG + '\nsummarization:\n  mode: model\n  endpoint: https://model.example/v1/chat/completions\n  model: example\n  api_key_env: UNSET_TEST_EMAIL_SUMMARY_KEY\n', encoding="utf-8")
            with patch("research_radar.cli.ChineseOfficialSource.scan", return_value=scan(observation())), patch("research_radar.cli.InternationalFeedSource.scan", return_value=ScanResult("cepr:CEPR", "CEPR", "working_paper", [], 1, "feed-snapshot")):
                code, digest = run(config, root / "monitor")
            self.assertEqual(code, 4)
            text = (root / "monitor" / "emails" / (digest.stem + ".txt")).read_text(encoding="utf-8")
            self.assertIn("等待模型配置", text)
            self.assertIn("本文研究企业纵向一体化与融资约束", text)


if __name__ == "__main__":
    unittest.main()
