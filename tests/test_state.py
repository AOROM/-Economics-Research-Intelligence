import tempfile
import unittest
from pathlib import Path

from research_radar.sources import ScanResult
from research_radar.state import apply_observations, empty_state, load_state, save_json_atomic


def observation(title="企业纵向一体化与融资约束", status="网络首发", doi="10.1234/a", source_id="zh:test", url="https://journal.example/a"):
    return {"source_id": source_id, "source_name": "测试期刊", "kind": "chinese_journal", "language": "zh", "journal": "测试期刊",
            "priority": "critical", "title": title, "authors": ["张三"], "doi": doi, "stable_id": url, "official_url": url,
            "visibility_source_url": "https://journal.example/online", "status": status, "published_online": "2026-09-18",
            "abstract": "本文研究企业纵向一体化与融资约束。使用 CSMAR 数据，采用多期双重差分。", "observed_at": "2026-09-18T09:00:00+08:00"}


def scan(*items):
    return ScanResult("zh:test", "测试期刊", "chinese_journal", list(items), 1, "official-surface")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.topic = {"statement": "企业纵向一体化与融资约束", "preferred_methods": ["Staggered DID"], "preferred_datasets": ["CSMAR"]}
        self.t1 = "2026-09-18T09:00:00+08:00"
        self.t2 = "2026-09-25T09:00:00+08:00"

    def test_first_scan_baseline_and_second_scan_new(self):
        state, changes = apply_observations(empty_state("m"), [scan(observation())], self.topic, self.t1)
        self.assertEqual(len(changes["baseline"]), 1)
        self.assertFalse(changes["new"])
        state2, changes2 = apply_observations(state, [scan(observation(), observation(title="新论文", doi="10.1234/b", url="https://journal.example/b"))], self.topic, self.t2)
        self.assertEqual(len(changes2["new"]), 1)
        self.assertEqual(len(state2["works"]), 2)

    def test_status_change_is_one_work(self):
        state, _ = apply_observations(empty_state("m"), [scan(observation())], self.topic, self.t1)
        changed = observation(status="正式出版", url="https://journal.example/formal-a")
        state, changes = apply_observations(state, [scan(changed)], self.topic, self.t2)
        self.assertEqual(len(state["works"]), 1)
        self.assertEqual(len(changes["updated"]), 1)
        self.assertEqual(len(next(iter(state["works"].values()))["versions"]), 2)

    def test_failed_source_state_is_preserved(self):
        state, _ = apply_observations(empty_state("m"), [scan(observation())], self.topic, self.t1)
        next_state, _ = apply_observations(state, [], self.topic, self.t2)
        self.assertEqual(next_state["source_scans"]["zh:test"]["last_successful_scan_at"], self.t1)

    def test_late_observed_old_official_date_is_new(self):
        state, _ = apply_observations(empty_state("m"), [scan()], self.topic, self.t1)
        late = observation(title="迟到的官网条目", doi="10.1234/late", url="https://journal.example/late")
        late["published_online"] = "2026-09-18"
        _, changes = apply_observations(state, [scan(late)], self.topic, self.t2)
        self.assertEqual(len(changes["new"]), 1)

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            save_json_atomic(path, empty_state("m"))
            self.assertEqual(load_state(path, "m")["monitor_id"], "m")

    def test_working_paper_to_journal_links_one_work(self):
        paper = observation(title="Credit Supply and Firm Boundaries", doi=None, source_id="cepr:dp", url="https://cepr.org/publications/dp1")
        paper.update({"source_name": "CEPR", "kind": "working_paper", "journal": None, "language": "en", "authors": ["Alice Smith"], "status": "Working Paper"})
        journal = observation(title="Credit Supply and Firm Boundaries", doi="10.1234/journal", source_id="journal:jf", url="https://journal.example/jf/1")
        journal.update({"source_name": "Journal of Finance", "kind": "english_journal", "journal": "Journal of Finance", "language": "en", "authors": ["Alice Smith"], "status": "Published"})
        state, _ = apply_observations(empty_state("m"), [ScanResult("cepr:dp", "CEPR", "working_paper", [paper], 1, "feed-snapshot"), ScanResult("journal:jf", "Journal of Finance", "english_journal", [], 1, "feed-snapshot")], self.topic, self.t1)
        state, changes = apply_observations(state, [ScanResult("journal:jf", "Journal of Finance", "english_journal", [journal], 1, "feed-snapshot")], self.topic, self.t2)
        self.assertEqual(len(state["works"]), 1)
        self.assertEqual(len(changes["updated"]), 1)
        work = next(iter(state["works"].values()))
        self.assertEqual(len(work["versions"]), 2)
        self.assertEqual(work["journal_publication_at"], "2026-09-18")

    def test_title_only_link_is_held_for_review(self):
        paper = observation(title="Credit Supply and Firm Boundaries", doi=None, source_id="cepr:dp", url="https://cepr.org/publications/dp1")
        paper.update({"source_name": "CEPR", "kind": "working_paper", "journal": None, "language": "en", "authors": [], "status": "Working Paper"})
        journal = observation(title="Credit Supply and Firm Boundaries", doi=None, source_id="journal:jf", url="https://journal.example/jf/1")
        journal.update({"source_name": "Journal of Finance", "kind": "english_journal", "journal": "Journal of Finance", "language": "en", "authors": [], "status": "Published"})
        state, _ = apply_observations(empty_state("m"), [ScanResult("cepr:dp", "CEPR", "working_paper", [paper], 1, "feed-snapshot")], self.topic, self.t1)
        state, changes = apply_observations(state, [ScanResult("journal:jf", "Journal of Finance", "english_journal", [journal], 1, "feed-snapshot")], self.topic, self.t2)
        self.assertEqual(len(state["works"]), 2)
        self.assertEqual(len(changes["possible_links"]), 1)


if __name__ == "__main__":
    unittest.main()
