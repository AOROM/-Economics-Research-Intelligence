import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_radar.config import summary_options, validate_email
from research_radar.documents import build_document, import_fulltext
from research_radar.state import apply_observations, empty_state
from research_radar.summaries import ModelError, extractive_summary, refresh_summaries, request_model, validate_model_summary
from test_state import observation, scan


NOW = "2026-09-19T09:00:00+08:00"
TOPIC = {"statement": "企业边界与融资约束", "preferred_datasets": ["CSMAR"]}
ABSTRACT = "本文研究企业边界与融资约束。使用2010—2020年企业样本和CSMAR数据。研究发现，融资成本降低2个百分点。异质性分析未发现小企业的显著变化。"


def prepared(abstract=ABSTRACT):
    obs = observation()
    obs["abstract"] = abstract
    state, changes = apply_observations(empty_state("test"), [scan(obs)], TOPIC, NOW)
    work = next(iter(state["works"].values()))
    return state, work, changes


def valid_payload(document):
    block = next(b for b in document["blocks"] if b["id"] == "abstract:3")
    return {"paper_type": "empirical", "claims": [{"field": "overview", "text": "论文报告融资成本降低2个百分点。",
             "evidence": [{"block_id": block["id"], "quote": block["text"]}]}]}


def model_config(**overrides):
    return {"topic": TOPIC, "summarization": {"mode": "model", "endpoint": "https://model.example/v1/chat/completions",
            "model": "configured-model", "api_key_env": "TEST_RADAR_KEY", **overrides}}


class SummaryTests(unittest.TestCase):
    def test_title_only_does_not_invent_paper_findings(self):
        _, work, _ = prepared(None)
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        self.assertEqual(document["scope"], "title-only")
        self.assertEqual(extractive_summary(document)["claims"], [])

    def test_extraction_keeps_negative_finding_and_exact_source(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        summary = extractive_summary(document)
        self.assertTrue(any("未发现小企业" in c["text"] for c in summary["claims"] if c["field"] == "findings"))
        for claim in summary["claims"]:
            for evidence in claim["evidence"]:
                self.assertIn(evidence["quote"], ABSTRACT)

    def test_literature_method_mentions_are_not_labeled_as_papers_method(self):
        _, work, _ = prepared("已有文献采用工具变量研究信贷。本文研究企业边界。")
        with tempfile.TemporaryDirectory() as temp:
            summary = extractive_summary(build_document(work, Path(temp)))
        self.assertFalse(any(c["field"] == "identification" for c in summary["claims"]))

    def test_background_does_not_displace_explicit_research_question(self):
        _, work, _ = prepared("这个问题具有重要意义。本文基于2010年企业数据，考察融资约束的影响。研究发现融资成本下降。")
        with tempfile.TemporaryDirectory() as temp:
            summary = extractive_summary(build_document(work, Path(temp)))
        overview = next(c for c in summary["claims"] if c["field"] == "overview")
        self.assertNotIn("这个问题具有重要意义", overview["text"])
        self.assertIn("本文基于2010年企业数据", overview["text"])

    def test_chinese_adjacent_dataset_name_produces_reading_hint(self):
        state, work, _ = prepared("本文使用CSMAR数据研究企业边界，同时介绍CSMARTool软件。")
        with tempfile.TemporaryDirectory() as temp:
            refresh_summaries(state, {"topic": TOPIC}, Path(temp), NOW)
        self.assertIn("CSMAR", work["analysis"]["datasets"])
        self.assertEqual(work["reading_relevance"]["scores"]["data"], 1)

    def test_model_rejects_invented_quote_and_numbers_adjacent_to_chinese(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        payload = valid_payload(document)
        self.assertEqual(validate_model_summary(payload, document)["method"], "model")
        bad = copy.deepcopy(payload)
        bad["claims"][0]["text"] = "论文报告融资成本降低20个百分点。"
        with self.assertRaisesRegex(ModelError, "数字"):
            validate_model_summary(bad, document)
        bad = copy.deepcopy(payload)
        bad["claims"][0]["evidence"][0]["quote"] = "原文没有出现过的融资成本结论。"
        with self.assertRaisesRegex(ModelError, "引文"):
            validate_model_summary(bad, document)

    def test_model_rejects_significance_upgrade(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        payload = valid_payload(document)
        payload["claims"][0].update(text="小企业融资约束显著改善。", evidence=[{"block_id": "abstract:4", "quote": "异质性分析未发现小企业的显著变化。"}])
        # Unreported significance must not become an affirmative effect.
        with self.assertRaises(ModelError):
            validate_model_summary(payload, document)

    def test_model_rejects_percent_to_percentage_point_conversion(self):
        _, work, _ = prepared("本文研究企业边界。研究发现融资成本降低2%。")
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        payload = {"paper_type": "empirical", "claims": [{"field": "overview", "text": "融资成本降低2个百分点。",
                   "evidence": [{"block_id": "abstract:2", "quote": "研究发现融资成本降低2%。"}]}]}
        with self.assertRaisesRegex(ModelError, "百分点"):
            validate_model_summary(payload, document)

    def test_cache_reused_when_topic_changes_and_history_saved(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_RADAR_KEY": "test-secret"}):
            workdir = Path(temp)
            result = validate_model_summary(valid_payload(build_document(work, workdir)), build_document(work, workdir))
            with patch("research_radar.summaries.request_model", return_value=result) as model:
                refresh_summaries(state, model_config(), workdir, NOW)
                refresh_summaries(state, model_config(), workdir, NOW)
                changed = model_config()
                changed["topic"] = {"statement": "就业与工资"}
                refresh_summaries(state, changed, workdir, NOW)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(len(list((workdir / "summaries").rglob("*.json"))), 1)
            self.assertNotIn("test-secret", (workdir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(work["reading_relevance"]["scores"]["topic"], 0)

    def test_model_failure_falls_back_and_retries_without_losing_paper(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_RADAR_KEY": "test-secret"}):
            workdir = Path(temp)
            with patch("research_radar.summaries.request_model", side_effect=ModelError("模型服务返回 HTTP 503")) as model:
                for _ in range(4):
                    refresh_summaries(state, model_config(), workdir, NOW)
            self.assertEqual(model.call_count, 3)
            self.assertEqual(work["summary_job"]["status"], "needs_review")
            self.assertEqual(work["summary"]["method"], "extractive")
            self.assertEqual(len(work["versions"]), 1)
            valid = validate_model_summary(valid_payload(build_document(work, workdir)), build_document(work, workdir))
            with patch("research_radar.summaries.request_model", return_value=valid):
                refresh_summaries(state, model_config(), workdir, NOW, retry=True)
            self.assertEqual(work["summary_job"]["status"], "ready")
            self.assertEqual(len(list((workdir / "summaries").rglob("*.json"))), 2)

    def test_budget_and_missing_key_keep_all_reading_cards(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True), patch("research_radar.summaries.request_model") as model:
            result = refresh_summaries(state, model_config(), Path(temp), NOW)
            model.assert_not_called()
            self.assertEqual(result["awaiting_configuration"], 1)
            self.assertTrue(work["summary"]["claims"])
            self.assertEqual(work["summary_job"]["attempts"], 0)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_RADAR_KEY": "test-secret"}), patch("research_radar.summaries.request_model") as model:
            result = refresh_summaries(state, model_config(max_model_calls=0), Path(temp), NOW)
            model.assert_not_called()
            self.assertEqual(result["pending"], 1)

    def test_accepted_summary_survives_failed_model_reconfiguration(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"TEST_RADAR_KEY": "test-secret"}):
            workdir = Path(temp)
            valid = validate_model_summary(valid_payload(build_document(work, workdir)), build_document(work, workdir))
            with patch("research_radar.summaries.request_model", return_value=valid):
                refresh_summaries(state, model_config(), workdir, NOW)
            accepted = copy.deepcopy(work["summary"])
            with patch("research_radar.summaries.request_model", side_effect=ModelError("bad response")):
                refresh_summaries(state, model_config(model="replacement-model"), workdir, NOW)
            self.assertEqual(work["summary"], accepted)

    def test_model_transport_is_bounded_and_uses_validated_json(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            document = build_document(work, Path(temp))
        class Response:
            status_code = 200
            content = b"small response"
            def json(self):
                return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(valid_payload(document))}}]}
        with patch.dict(os.environ, {"TEST_RADAR_KEY": "test-secret"}), patch("research_radar.summaries.requests.post", return_value=Response()) as post:
            output = request_model(document, summary_options(model_config()))
        self.assertEqual(output["method"], "model")
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertIn("timeout", post.call_args.kwargs)

    def test_header_injection_and_insecure_model_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            validate_email({"email": {"subject_prefix": "subject\r\nBcc: injected@example.com"}})
        with self.assertRaises(ValueError):
            summary_options(model_config(endpoint="http://remote.example/chat"))


class DocumentTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "optional PDF dependency not installed")
    def test_real_pdf_text_import_has_file_page_evidence(self):
        # Small synthetic PDF with an actual text layer; no third-party paper.
        stream = b"BT /F1 12 Tf 40 700 Td (This paper examines firm boundaries and financing constraints. We use a sample of firms. We find lower financing costs and no significant effect for small firms.) Tj ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1200 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                   f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"]
        pdf, offsets = b"%PDF-1.4\n", [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(pdf))
            pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        start = len(pdf)
        pdf += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
        pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
        pdf += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
        _, work, _ = prepared(None)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "paper.pdf"
            source.write_bytes(pdf)
            import_fulltext(source, work, root)
            document = build_document(work, root)
            self.assertEqual(document["scope"], "provided-full-text")
            self.assertTrue(any("正文第 1 页" in b["location"] and "financing costs" in b["text"] for b in document["blocks"]))

    def test_user_text_is_version_bound_and_fulltext_upgrade_preserves_history(self):
        state, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            refresh_summaries(state, {"topic": TOPIC}, workdir, NOW)
            source = workdir / "paper.txt"
            source.write_text("本文研究企业边界与融资约束。" + "研究发现融资成本下降，但小企业的变化不显著。" * 10, encoding="utf-8")
            import_fulltext(source, work, workdir)
            refresh_summaries(state, {"topic": TOPIC}, workdir, NOW)
            self.assertEqual(work["summary"]["scope"], "provided-full-text")
            self.assertEqual(len(list((workdir / "summaries").rglob("*.json"))), 2)
            self.assertEqual(len(work["versions"]), 1)
            work["versions"][-1]["fingerprint"] = "different-paper-version"
            document = build_document(work, workdir)
            self.assertEqual(document["scope"], "title-and-abstract")
            self.assertIn("另一论文版本", document["notes"][0])

    def test_partial_body_and_budget_are_disclosed(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            source = workdir / "paper.txt"
            source.write_text("本文研究企业融资。" * 1000, encoding="utf-8")
            import_fulltext(source, work, workdir)
            document = build_document(work, workdir, max_chars=2000)
            self.assertEqual(document["scope"], "provided-full-text-partial")
            self.assertLess(len(document["blocks"]), document["total_blocks"])
            self.assertLessEqual(sum(len(b["text"]) for b in document["blocks"]), 2000)

    def test_corrupt_fulltext_keeps_abstract_and_no_partial_injected_blocks(self):
        _, work, _ = prepared()
        with tempfile.TemporaryDirectory() as temp:
            workdir = Path(temp)
            path = workdir / "fulltexts" / (work["canonical_work_id"] + ".json")
            path.parent.mkdir()
            path.write_text(json.dumps({"version_fingerprint": work["versions"][-1]["fingerprint"],
                "source_url": work["versions"][-1]["official_url"], "pages": [{"text": "half a body"}, {}]}), encoding="utf-8")
            document = build_document(work, workdir)
            self.assertEqual(document["scope"], "title-and-abstract")
            self.assertFalse(any(b["id"].startswith("body-") for b in document["blocks"]))


if __name__ == "__main__":
    unittest.main()
