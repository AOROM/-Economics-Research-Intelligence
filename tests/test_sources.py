from pathlib import Path
import unittest

from research_radar.sources import ChineseOfficialSource, SourceError, parse_feed


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, url, content):
        self.url = url
        self.content = content.encode("utf-8")
        self.text = content

    def raise_for_status(self):
        return None


class FakeSession:
    def get(self, url, **kwargs):
        file = {
            "https://journal.example/online": "chinese_page1.html",
            "https://journal.example/online?page=2": "chinese_page2.html",
            "https://journal.example/paper/a1": "chinese_article.html",
            "https://journal.example/paper/a2": "chinese_article.html",
        }[url]
        return FakeResponse(url, (FIXTURES / file).read_text(encoding="utf-8"))


class SourceTests(unittest.TestCase):
    def journal(self):
        return {"name": "测试经济学期刊", "homepage": "https://journal.example", "priority": "critical", "surfaces": [{
            "label": "网络首发", "url": "https://journal.example/online", "item_selector": ".paper",
            "title_selector": ".title", "link_selector": ".title", "author_selector": ".authors",
            "date_selector": ".date", "next_selector": ".next", "max_pages": 3,
            "article": {"abstract_selector": ".abstract", "doi_selector": ".doi"},
        }]}

    def test_official_pages_and_pagination(self):
        scan = ChineseOfficialSource(self.journal(), FakeSession()).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(scan.pages, 2)
        self.assertEqual(len(scan.observations), 2)
        self.assertEqual(scan.observations[0]["doi"], "10.1234/test.1")
        self.assertEqual(scan.observations[0]["published_online"], "2026-09-18")

    def test_official_host_enforced(self):
        journal = self.journal()
        journal["surfaces"][0]["url"] = "https://untrusted.example/online"
        with self.assertRaises(SourceError):
            ChineseOfficialSource(journal, FakeSession()).scan("2026-09-18T09:00:00+08:00")

    def test_cepr_feed(self):
        source = {"id": "cepr:dp", "provider": "cepr", "name": "CEPR", "feed_url": "https://cepr.org/rss/discussion-paper"}
        items = parse_feed((FIXTURES / "cepr.xml").read_text(encoding="utf-8"), source, "2026-09-18T09:00:00+08:00")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["stable_id"], "dp12345")
        self.assertEqual(items[0]["kind"], "working_paper")


if __name__ == "__main__":
    unittest.main()
