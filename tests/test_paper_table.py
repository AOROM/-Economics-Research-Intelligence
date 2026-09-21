import base64
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_radar.paper_table import (GitHubPaperTable, HEADERS, render_paper_table,
                                        summarized_paper_rows, write_paper_table)
from research_radar.summaries import refresh_summaries
from test_summaries import NOW, TOPIC, prepared


def table_config(name="测试期刊"):
    return {
        "topic": TOPIC,
        "chinese_monitor": {"journals": [{"name": name}]},
        "international_monitor": {"sources": []},
    }


class PaperTableTests(unittest.TestCase):
    def test_table_contains_only_configured_papers_with_completed_summaries(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            refresh_summaries(state, table_config(), Path(temp), NOW)
            content, count = render_paper_table(state, table_config())
            destination = Path(temp) / "papers.csv"
            written = write_paper_table(state, table_config(), destination)
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(count, 1)
        self.assertEqual(written, 1)
        self.assertEqual(tuple(rows[0]), HEADERS)
        self.assertEqual(rows[0]["论文题目"], work["title"])
        self.assertEqual(rows[0]["来源期刊"], "测试期刊")
        self.assertEqual(rows[0]["作者"], "张三")
        self.assertIn("融资成本降低2个百分点", rows[0]["摘要"])

        self.assertEqual(summarized_paper_rows(state, table_config("已移除期刊")), [])

    def test_unsummarized_and_title_only_records_are_excluded(self):
        state, _, _ = prepared()
        self.assertEqual(summarized_paper_rows(state, table_config()), [])
        title_only, _, _ = prepared(None)
        with tempfile.TemporaryDirectory() as temp:
            refresh_summaries(title_only, table_config(), Path(temp), NOW)
        self.assertEqual(summarized_paper_rows(title_only, table_config()), [])

    def test_missing_source_abstract_uses_labeled_overview_and_csv_formula_is_neutralized(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            refresh_summaries(state, table_config(), Path(temp), NOW)
        event = work["versions"][-1]
        event["title"] = "=unsafe title"
        event["abstract"] = None
        row = summarized_paper_rows(state, table_config())[0]
        self.assertTrue(row["论文题目"].startswith("'="))
        self.assertTrue(row["摘要"].startswith("【来源未提供摘要；以下为系统提炼的内容概括】"))

    def test_repository_publisher_updates_only_when_content_changes(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "token"}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", env, clear=True):
            source = Path(temp) / "papers.csv"
            source.write_text(",".join(HEADERS) + "\n新论文,期刊,作者,摘要\n", encoding="utf-8")
            publisher = GitHubPaperTable()
            current = {"encoding": "base64", "content": base64.b64encode(b"old").decode("ascii"), "sha": "blob-sha"}
            with patch.object(publisher, "_request", side_effect=[current, {"content": {}}]) as request:
                self.assertEqual(publisher.publish(source), "updated")
            put = request.call_args_list[1]
            self.assertEqual(put.args[0], "PUT")
            self.assertEqual(put.args[2]["sha"], "blob-sha")
            self.assertIn("[skip ci]", put.args[2]["message"])
            self.assertEqual(base64.b64decode(put.args[2]["content"]), source.read_bytes())

            same = {"encoding": "base64", "content": base64.b64encode(source.read_bytes()).decode("ascii"), "sha": "same"}
            with patch.object(publisher, "_request", return_value=same) as request:
                self.assertEqual(publisher.publish(source), "unchanged")
            request.assert_called_once()

    def test_repository_publisher_accepts_a_specific_audit_commit_message(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "token"}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", env, clear=True):
            source = Path(temp) / "status.json"
            source.write_text("{}\n", encoding="utf-8")
            publisher = GitHubPaperTable(
                path="reports/weekly-run-status.json",
                commit_message="Record successful weekly monitor run [skip ci]",
            )
            with patch.object(publisher, "_request", side_effect=[None, {}]) as request:
                self.assertEqual(publisher.publish(source), "created")
            self.assertEqual(request.call_args_list[1].args[2]["message"],
                             "Record successful weekly monitor run [skip ci]")

    def test_repository_publisher_reads_large_existing_file_through_blob_api(self):
        env = {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_TOKEN": "token"}
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", env, clear=True):
            source = Path(temp) / "papers.csv"
            source.write_text(",".join(HEADERS) + "\n", encoding="utf-8")
            publisher = GitHubPaperTable()
            current = {"encoding": "none", "content": "", "sha": "large-blob-sha"}
            blob = {"encoding": "base64", "content": base64.b64encode(source.read_bytes()).decode("ascii")}
            with patch.object(publisher, "_request", side_effect=[current, blob]) as request:
                self.assertEqual(publisher.publish(source), "unchanged")
            self.assertEqual(request.call_args_list[1].args[:2], ("GET", "/git/blobs/large-blob-sha"))


if __name__ == "__main__":
    unittest.main()
