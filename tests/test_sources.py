from pathlib import Path
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from research_radar.normalize import url_key
from research_radar.sources import (CrossrefJournalSource, ChineseOfficialSource, SourceError,
                                    parse_feed, request_official, split_authors)


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, url, content):
        self.url = url
        self.content = content.encode("utf-8")
        self.text = content
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)


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
    def test_retry_after_is_honored_for_rate_limit(self):
        limited = FakeResponse("https://api.crossref.org/works", "{}")
        limited.status_code = 429
        limited.headers = {"Retry-After": "2"}
        ready = FakeResponse("https://api.crossref.org/works", "{}")

        class RetrySession:
            def __init__(inner):
                inner.responses = [limited, ready]
            def get(inner, url, **kwargs):
                return inner.responses.pop(0)

        with patch("research_radar.sources.time.sleep") as sleep:
            response = request_official("https://api.crossref.org/works", ["api.crossref.org"], RetrySession())
        self.assertIs(response, ready)
        sleep.assert_called_once_with(2.0)

    def test_spaced_chinese_name_is_not_split_into_single_character_authors(self):
        authors = split_authors("李珍珍　杨　柳　杨甜甜　李　明")
        self.assertEqual(authors, ["李珍珍 杨 柳 杨甜甜 李 明"])

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

    def test_official_article_links_and_citation_metadata(self):
        class LinkSession:
            def get(self, url, **kwargs):
                pages = {
                    "https://journal.example/current": '<a href="/CN/abstract/abstract42.shtml">企业边界与融资约束</a><a href="/CN/abstract/abstract42.shtml">摘要</a><a href="/news">征稿启事</a>',
                    "https://journal.example/CN/abstract/abstract42.shtml": '<meta name="citation_author" content="张三"><meta name="citation_author" content="李四"><meta name="citation_doi" content="10.1234/example.42"><meta name="citation_abstract" content="本文研究企业边界。"><meta name="citation_online_date" content="2026/09/18">',
                }
                return FakeResponse(url, pages[url])

        journal = {"name": "测试经济学期刊", "homepage": "https://journal.example", "surfaces": [{
            "label": "当期目录", "url": "https://journal.example/current",
            "link_path_regex": r"/CN/abstract/abstract[0-9]+\.shtml", "article_metadata": True,
        }]}
        scan = ChineseOfficialSource(journal, LinkSession()).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(len(scan.observations), 1)
        self.assertEqual(scan.observations[0]["authors"], ["张三", "李四"])
        self.assertEqual(scan.observations[0]["doi"], "10.1234/example.42")
        self.assertEqual(scan.observations[0]["published_online"], "2026-09-18")

    def test_no_matching_article_links_is_coverage_failure(self):
        class EmptySession:
            def get(self, url, **kwargs):
                return FakeResponse(url, '<a href="/news">征稿启事</a>')

        journal = {"name": "测试经济学期刊", "homepage": "https://journal.example", "surfaces": [{
            "label": "当期目录", "url": "https://journal.example/current",
            "link_path_regex": r"/CN/abstract/abstract[0-9]+\.shtml",
        }]}
        with self.assertRaisesRegex(SourceError, "No article links matched"):
            ChineseOfficialSource(journal, EmptySession()).scan("2026-09-18T09:00:00+08:00")

    def test_same_host_http_article_link_is_upgraded(self):
        class MixedLinkSession:
            def get(self, url, **kwargs):
                page = '<div class="paper"><a class="title" href="http://journal.example/paper/a1">企业融资约束研究</a></div>'
                return FakeResponse(url, page)

        journal = {"name": "测试经济学期刊", "homepage": "https://journal.example", "surfaces": [{
            "label": "当期目录", "url": "https://journal.example/current", "item_selector": ".paper",
            "title_selector": ".title", "link_selector": ".title",
        }]}
        scan = ChineseOfficialSource(journal, MixedLinkSession()).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(scan.observations[0]["official_url"], "https://journal.example/paper/a1")

    def test_ajcass_current_issue_api_and_detail(self):
        class ApiSession:
            def get(self, url, **kwargs):
                payload = {"code": 200, "data": {"year": 2026, "issue": 7, "issueInfoList": [
                    {"id": 42, "title": "企业边界与融资约束", "authors": "张三，李四", "year": 2026, "issue": 7}
                ]}}
                return FakeResponse(url, json.dumps(payload, ensure_ascii=False))

            def post(self, url, **kwargs):
                self.body = kwargs["json"]
                payload = {"code": 200, "data": {"issueContentInfoResult": {
                    "authors": "张三，李四", "abstract": "<p>本文研究企业边界。</p>", "doi": "10.1234/api.42"
                }}}
                return FakeResponse(url, json.dumps(payload, ensure_ascii=False))

        journal = {
            "name": "测试经济学期刊", "homepage": "https://journal.example", "adapter": "ajcass_api",
            "allowed_hosts": ["journal.example", "api.example"], "api_url": "https://api.example/api",
            "journal_id": 123, "detail_url_template": "https://journal.example/#/issue?id={id}&year={year}&issue={issue}",
        }
        scan = ChineseOfficialSource(journal, ApiSession()).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(len(scan.observations), 1)
        self.assertEqual(scan.observations[0]["authors"], ["张三", "李四"])
        self.assertEqual(scan.observations[0]["abstract"], "本文研究企业边界。")
        self.assertEqual(scan.observations[0]["doi"], "10.1234/api.42")
        self.assertIn("#/issue?", scan.observations[0]["official_url"])

    def test_pku_issue_index_to_article_downloads(self):
        issue_id = "a" * 32

        class PkuSession:
            def get(self, url, **kwargs):
                if url.endswith("index.htm"):
                    return FakeResponse(url, f'<a href="{issue_id}.htm">经济学（季刊）第26卷第4期</a>')
                page = '''<meta name="PubDate" content="2026-07-30 06:31:00">
                <p>数据收集、个性化定价与企业创新激励<em>(<a href="/docs/paper.pdf">全文下载</a>)</em></p>
                <p>…………尹振东 马昕 寇宗来/1001</p>'''
                return FakeResponse(url, page)

        journal = {
            "name": "经济学（季刊）", "homepage": "https://nsd.pku.edu.cn/index.htm", "adapter": "pku_issue",
            "issue_index_url": "https://nsd.pku.edu.cn/index.htm",
            "issue_link_regex": rf"/{issue_id}\.htm", "allowed_hosts": ["nsd.pku.edu.cn"],
        }
        scan = ChineseOfficialSource(journal, PkuSession()).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(scan.pages, 2)
        self.assertEqual(scan.observations[0]["title"], "数据收集、个性化定价与企业创新激励")
        self.assertEqual(scan.observations[0]["authors"], ["尹振东", "马昕", "寇宗来"])
        self.assertEqual(scan.observations[0]["published_online"], "2026-07-30")

    def test_hash_route_is_part_of_stable_url_key(self):
        first = url_key("https://journal.example/#/issue?id=1&year=2026")
        second = url_key("https://journal.example/#/issue?id=2&year=2026")
        self.assertNotEqual(first, second)

    def test_cepr_feed(self):
        source = {"id": "cepr:dp", "provider": "cepr", "name": "CEPR", "feed_url": "https://cepr.org/rss/discussion-paper"}
        items = parse_feed((FIXTURES / "cepr.xml").read_text(encoding="utf-8"), source, "2026-09-18T09:00:00+08:00")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["stable_id"], "dp12345")
        self.assertEqual(items[0]["kind"], "working_paper")

    def test_crossref_journal_uses_bounded_index_window_and_publisher_link(self):
        payload = {"message": {"total-results": 1, "items": [{
            "DOI": "10.1234/TEST.1", "title": ["Firm Boundaries and Credit"],
            "author": [{"given": "Alice", "family": "Smith"}],
            "published-online": {"date-parts": [[2026, 9, 17]]},
            "URL": "https://api.crossref.org/works/10.1234/test.1",
            "abstract": "<jats:p>We study firm boundaries.</jats:p>",
        }]}}

        class CrossrefSession:
            def get(inner, url, **kwargs):
                inner.url = url
                return FakeResponse(url, json.dumps(payload))

        session = CrossrefSession()
        source = {"id": "crossref:0022-1082", "provider": "crossref", "name": "Journal of Finance",
                  "issn": "0022-1082", "tier": "TOP", "api_url": "https://api.crossref.org"}
        scan = CrossrefJournalSource(source, "2026-09-11T09:00:00+08:00", session).scan("2026-09-18T09:00:00+08:00")
        query = parse_qs(urlsplit(session.url).query)
        self.assertIn("from-index-date:2026-08-28", query["filter"][0])
        self.assertIn("until-index-date:2026-09-18", query["filter"][0])
        self.assertIn("from-pub-date:2026-03-22", query["filter"][0])
        self.assertIn("until-pub-date:2026-09-18", query["filter"][0])
        self.assertEqual(scan.coverage.split(";")[0], "crossref-incremental")
        self.assertEqual(scan.observations[0]["official_url"], "https://doi.org/10.1234/test.1")
        self.assertEqual(scan.observations[0]["abstract"], "We study firm boundaries.")
        self.assertEqual(scan.observations[0]["tier"], "TOP")

    def test_crossref_empty_window_is_success_and_oversized_window_fails(self):
        class CrossrefSession:
            def __init__(inner, total):
                inner.total = total
            def get(inner, url, **kwargs):
                return FakeResponse(url, json.dumps({"message": {"total-results": inner.total, "items": []}}))

        source = {"provider": "crossref", "name": "Economic Journal", "issn": "0013-0133",
                  "api_url": "https://api.crossref.org"}
        scan = CrossrefJournalSource(source, None, CrossrefSession(0)).scan("2026-09-18T09:00:00+08:00")
        self.assertEqual(scan.observations, [])
        self.assertTrue(scan.coverage.startswith("crossref-baseline"))
        with self.assertRaisesRegex(SourceError, "safe one-page limit"):
            CrossrefJournalSource(source, None, CrossrefSession(1001)).scan("2026-09-18T09:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
