import unittest

from research_radar.analyzer import analyze


class AnalyzerTests(unittest.TestCase):
    def test_evidence_bound_extraction(self):
        observation = {"title": "企业纵向一体化与融资约束", "abstract": "本文研究银行信贷对企业纵向一体化的影响。使用 CSMAR 数据，采用多期双重差分。结果表明政策冲击提高企业投资。", "official_url": "https://example.org/a"}
        result = analyze(observation, {"statement": "企业边界与融资约束", "preferred_methods": ["Staggered DID"], "preferred_datasets": ["CSMAR"]})
        self.assertIn("firm_boundaries", result["concepts"])
        self.assertIn("Staggered DID", result["methods"])
        self.assertIn("CSMAR", result["datasets"])
        self.assertIsNone(result["design"]["main_x"])

    def test_english_did_verb_is_not_method(self):
        result = analyze({"title": "What did firms do?", "abstract": "Firms did not invest.", "official_url": "https://example.org/a"}, {"statement": "firm investment"})
        self.assertNotIn("DID", result["methods"])


if __name__ == "__main__":
    unittest.main()
