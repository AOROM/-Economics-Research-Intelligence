"""Official Chinese journal pages and explicitly configured international feeds."""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from .config import official_host, within_hosts
from .normalize import extract_doi, url_key


class SourceError(RuntimeError):
    pass


@dataclass
class ScanResult:
    source_id: str
    source_name: str
    kind: str
    observations: list[dict]
    pages: int
    coverage: str


USER_AGENT = "Mozilla/5.0 (compatible; EconomicsResearchRadar/0.2; official-journal-monitor)"


def request_official(
    url: str,
    hosts: list[str],
    session: requests.Session | None = None,
    *,
    allow_http: bool = False,
    method: str = "GET",
    json_data: dict | None = None,
):
    if not within_hosts(url, hosts, allow_http=allow_http):
        raise SourceError(f"URL outside configured official hosts: {url}")
    session = session or requests.Session()
    last_error = None
    for attempt in range(3):
        try:
            caller = session.post if method.upper() == "POST" else session.get
            kwargs = {"timeout": 20, "headers": {"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}}
            if json_data is not None:
                kwargs["json"] = json_data
            response = caller(url, **kwargs)
            if not within_hosts(response.url, hosts, allow_http=allow_http):
                raise SourceError(f"Redirect outside configured official hosts: {response.url}")
            response.raise_for_status()
            if len(response.content) > 5_000_000:
                raise SourceError("Response exceeds 5 MB limit")
            return response
        except (requests.RequestException, SourceError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise SourceError(f"Official source failed: {url}: {last_error}")


def fetch(
    url: str,
    hosts: list[str],
    session: requests.Session | None = None,
    *,
    allow_http: bool = False,
) -> str:
    response = request_official(url, hosts, session, allow_http=allow_http)
    encoding = getattr(response, "encoding", None)
    if not encoding or encoding.casefold() in {"iso-8859-1", "ascii"}:
        encoding = getattr(response, "apparent_encoding", None) or "utf-8"
    try:
        return response.content.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return response.text


def fetch_json(
    url: str,
    hosts: list[str],
    session: requests.Session | None = None,
    *,
    method: str = "GET",
    json_data: dict | None = None,
) -> dict:
    response = request_official(url, hosts, session, method=method, json_data=json_data)
    try:
        payload = response.json() if hasattr(response, "json") else json.loads(response.text)
    except (TypeError, ValueError) as exc:
        raise SourceError(f"Official API returned invalid JSON: {url}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("code") not in {None, 200}:
        raise SourceError(f"Official API returned an error: {url}: {payload.get('msg') if isinstance(payload, dict) else 'invalid payload'}")
    return payload


def resolved_link(base: str, href: str) -> str:
    """Resolve a link and upgrade same-host HTTP links emitted by an HTTPS page."""
    url = urljoin(base, href)
    base_parts, parts = urlsplit(base), urlsplit(url)
    if base_parts.scheme == "https" and parts.scheme == "http" and base_parts.hostname == parts.hostname:
        url = urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return url


def selected_text(node, selector: str | None) -> str | None:
    if not selector:
        return None
    found = node.select_one(selector)
    return found.get_text(" ", strip=True) if found else None


def selected_link(node, selector: str | None, base: str) -> str | None:
    found = node.select_one(selector) if selector else None
    return resolved_link(base, found.get("href", "")) if found and found.get("href") else None


def selected_attribute(node, selector: str | None, attribute: str | None) -> str | None:
    if not selector or not attribute:
        return None
    found = node.select_one(selector)
    return found.get(attribute, "").strip() or None if found else None


def split_authors(value: str | None) -> list[str]:
    value = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    parts = [v.strip() for v in re.split(r"\s*(?:,|，|;|；|、|\band\b|和|\u3000+)\s*", value) if v.strip()]
    if len(parts) == 1 and re.fullmatch(r"[\u3400-\u9fff（）()·\s]+", value) and re.search(r"\s", value):
        parts = [v for v in re.split(r"\s+", value) if v]
    if any(re.fullmatch(r"[\u3400-\u9fff]", part) for part in parts):
        # Typesetting sometimes spaces out two-character names (杨　柳).
        # Preserve the original author line when boundaries are ambiguous.
        return [" ".join(value.split())]
    return parts


def date_text(value: str | None) -> str | None:
    match = re.search(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", value or "")
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def article_links(soup: BeautifulSoup, surface: dict, base: str) -> list[tuple[str, str, object]]:
    """Find article links on a known official page by their verified URL shape."""
    pattern = re.compile(surface["link_path_regex"])
    matches: dict[str, tuple[str, str, object]] = {}
    for anchor in soup.select("a[href]"):
        article_url = resolved_link(base, anchor["href"])
        if not pattern.fullmatch(urlsplit(article_url).path):
            continue
        title = anchor.get_text(" ", strip=True)
        if len(title) < 8 or title in {"摘要", "全文", "HTML 全文", "PDF 全文"}:
            continue
        key = url_key(article_url)
        if key and (key not in matches or len(title) > len(matches[key][0])):
            matches[key] = (title, article_url, anchor)
    return list(matches.values())


def citation_metadata(article: BeautifulSoup) -> dict:
    values: dict[str, list[str]] = {}
    for tag in article.select("meta[name][content]"):
        value = tag.get("content", "").strip()
        if value:
            values.setdefault(tag.get("name", "").casefold(), []).append(value)

    def meta(*names: str) -> str | None:
        for name in names:
            matches = values.get(name.casefold()) or []
            if matches:
                return matches[0]
        return None

    return {
        "authors": values.get("citation_author", []) or split_authors(meta("author")),
        "abstract": meta("citation_abstract", "DC.description", "description"),
        "doi": extract_doi(meta("citation_doi", "prism.doi", "DOI")),
        "date": meta("citation_online_date", "citation_date", "citation_publication_date", "prism.publicationDate"),
    }


class ChineseOfficialSource:
    def __init__(self, journal: dict, session: requests.Session | None = None):
        self.journal = journal
        self.session = session or requests.Session()
        self.allow_http = journal.get("allow_http") is True
        self.hosts = journal.get("allowed_hosts") or [official_host(journal["homepage"], allow_http=self.allow_http)]
        self.source_id = "zh:" + journal["name"]

    def scan(self, observed_at: str) -> ScanResult:
        adapter = self.journal.get("adapter", "html")
        if adapter == "ajcass_api":
            return self._scan_ajcass(observed_at)
        if adapter == "pku_issue":
            return self._scan_pku_issue(observed_at)
        return self._scan_html(observed_at)

    def _observation(
        self,
        observed_at: str,
        *,
        title: str,
        article_url: str,
        visibility_url: str,
        status: str,
        stable_id: str | None,
        authors: list[str] | None = None,
        doi: str | None = None,
        published: str | None = None,
        abstract: str | None = None,
    ) -> dict:
        return {
            "source_id": self.source_id, "source_name": self.journal["name"],
            "kind": "chinese_journal", "language": "zh", "journal": self.journal["name"],
            "priority": self.journal.get("priority", "normal"), "title": " ".join(title.split()),
            "authors": authors or [], "doi": extract_doi(doi),
            "stable_id": stable_id or url_key(article_url),
            "official_url": article_url, "visibility_source_url": visibility_url,
            "status": status, "published_online": date_text(published),
            "abstract": " ".join(abstract.split()) if abstract else None, "observed_at": observed_at,
        }

    def _scan_html(self, observed_at: str) -> ScanResult:
        observations: list[dict] = []
        pages = 0
        detail_failures = 0
        empty_surfaces: list[str] = []
        for surface in self.journal["surfaces"]:
            current = surface["url"]
            visited: set[str] = set()
            max_pages = int(surface.get("max_pages", 20))
            surface_count = 0
            while current:
                key = url_key(current)
                if key in visited:
                    raise SourceError(f"Pagination loop on {self.journal['name']}: {current}")
                if len(visited) >= max_pages:
                    raise SourceError("Configured pagination limit reached")
                visited.add(key or current)
                soup = BeautifulSoup(fetch(current, self.hosts, self.session, allow_http=self.allow_http), "html.parser")
                pages += 1
                if surface.get("link_path_regex"):
                    items = article_links(soup, surface, current)
                else:
                    items = [(selected_text(item, surface["title_selector"]),
                              selected_link(item, surface["link_selector"], current), item)
                             for item in soup.select(surface["item_selector"])]
                for title, article_url, item in items:
                    if not title or not article_url:
                        continue
                    strip_pattern = surface.get("title_strip_regex")
                    title = re.sub(strip_pattern, "", title).strip() if strip_pattern else title.strip()
                    if len(title) < int(surface.get("minimum_title_length", 4)):
                        continue
                    if not within_hosts(article_url, self.hosts, allow_http=self.allow_http):
                        raise SourceError(f"Article URL outside official hosts: {article_url}")
                    detail = surface.get("article") or {}
                    article_html = None
                    if detail or surface.get("article_metadata"):
                        try:
                            article_html = fetch(article_url, self.hosts, self.session, allow_http=self.allow_http)
                        except SourceError:
                            if surface.get("article_metadata_required"):
                                raise
                            detail_failures += 1
                    article = BeautifulSoup(article_html, "html.parser") if article_html else None
                    metadata = citation_metadata(article) if article else {}
                    abstract = selected_text(item, surface.get("abstract_selector"))
                    abstract = selected_attribute(item, surface.get("abstract_selector"), surface.get("abstract_attribute")) or abstract
                    if article:
                        abstract = selected_text(article, detail.get("abstract_selector")) or metadata.get("abstract") or abstract
                    doi = extract_doi(selected_text(item, surface.get("doi_selector")))
                    if not doi and article:
                        doi = metadata.get("doi") or extract_doi(selected_text(article, detail.get("doi_selector")) or article_html)
                    authors = selected_text(item, surface.get("author_selector")) or (selected_text(article, detail.get("author_selector")) if article else None)
                    author_list = split_authors(authors) or metadata.get("authors", [])
                    published = selected_text(item, surface.get("date_selector")) or (selected_text(article, detail.get("date_selector")) if article else None) or metadata.get("date")
                    observations.append(self._observation(
                        observed_at, title=title, article_url=article_url, visibility_url=current,
                        status=surface["label"], stable_id=item.get("data-article-id") or item.get("id") or url_key(article_url),
                        authors=author_list, doi=doi, published=published, abstract=abstract,
                    ))
                    surface_count += 1
                next_selector = surface.get("next_selector")
                next_node = soup.select_one(next_selector) if next_selector else None
                next_url = resolved_link(current, next_node.get("href", "")) if next_node and next_node.get("href") else None
                if next_node and not next_url:
                    raise SourceError(f"Dynamic pagination requires a custom adapter: {current}")
                if next_url and not within_hosts(next_url, self.hosts, allow_http=self.allow_http):
                    raise SourceError(f"Pagination left official hosts: {next_url}")
                if next_url and len(visited) >= max_pages:
                    raise SourceError(f"Pagination exceeded max_pages={max_pages}: {current}")
                current = next_url
            if not surface_count:
                empty_surfaces.append(surface["label"])
        if not observations:
            raise SourceError(f"No article links matched the configured official surfaces: {self.journal['name']}")
        notes = []
        if empty_surfaces:
            notes.append("empty: " + ", ".join(empty_surfaces))
        if detail_failures:
            notes.append(f"{detail_failures} detail pages unavailable")
        coverage = "official HTML surfaces" + ("; " + "; ".join(notes) if notes else "")
        return ScanResult(self.source_id, self.journal["name"], "chinese_journal", observations, pages, coverage)

    def _scan_ajcass(self, observed_at: str) -> ScanResult:
        api = self.journal["api_url"].rstrip("/")
        journal_id = int(self.journal["journal_id"])
        current_url = api + "/SiteWebApi/GetCurrentPeriod?" + urlencode({"JournalID": journal_id})
        payload = fetch_json(current_url, self.hosts, self.session)
        data = payload.get("data") or {}
        items = data.get("issueInfoList") or []
        if not isinstance(items, list) or not items:
            raise SourceError(f"Official AJCASS API returned no current-issue articles: {self.journal['name']}")
        if len(items) > 100:
            raise SourceError(f"Official AJCASS API returned an implausible current-issue size: {len(items)}")
        observations = []
        pages = 1
        detail_failures = 0
        for item in items:
            content_id = item.get("contentId") or item.get("id")
            title = BeautifulSoup(str(item.get("title") or ""), "html.parser").get_text(" ", strip=True)
            if not content_id or len(title) < 4:
                continue
            year = int(item.get("year") or data.get("year") or 0)
            issue = int(item.get("issue") or data.get("issue") or 0)
            details: dict = {}
            if self.journal.get("fetch_details", True):
                uses_context = self.journal.get("detail_uses_issue_context", True)
                body = {
                    "JournalID": journal_id, "contentId": int(content_id), "channelId": 0,
                    "dataShowType": 1, "dataSourceType": 3,
                    "issue": issue if uses_context else 0, "year": year if uses_context else 0,
                }
                try:
                    detail_payload = fetch_json(api + "/SiteWebApi/GetContentInfo", self.hosts, self.session, method="POST", json_data=body)
                    details = ((detail_payload.get("data") or {}).get("issueContentInfoResult") or {})
                    pages += 1
                except SourceError:
                    detail_failures += 1
            authors_text = details.get("authors") or item.get("authors") or ""
            abstract = BeautifulSoup(str(details.get("abstract") or ""), "html.parser").get_text(" ", strip=True) or None
            article_url = self.journal["detail_url_template"].format(
                id=content_id, content_id=content_id, year=year, issue=issue,
            )
            if not within_hosts(article_url, self.hosts):
                raise SourceError(f"AJCASS detail URL outside official hosts: {article_url}")
            observations.append(self._observation(
                observed_at, title=title, article_url=article_url, visibility_url=current_url,
                status=self.journal.get("label", "当期目录"), stable_id=str(content_id),
                authors=split_authors(authors_text), doi=details.get("doi"), abstract=abstract,
            ))
        if not observations:
            raise SourceError(f"Official AJCASS API entries lacked usable identifiers: {self.journal['name']}")
        coverage = "official AJCASS current-issue API"
        if detail_failures:
            coverage += f"; {detail_failures} detail records unavailable"
        return ScanResult(self.source_id, self.journal["name"], "chinese_journal", observations, pages, coverage)

    def _scan_pku_issue(self, observed_at: str) -> ScanResult:
        index_url = self.journal["issue_index_url"]
        index = BeautifulSoup(fetch(index_url, self.hosts, self.session), "html.parser")
        issue_pattern = re.compile(self.journal["issue_link_regex"])
        title_pattern = re.compile(self.journal.get("issue_title_regex", r"第\s*\d+\s*卷第\s*\d+\s*期"))
        candidates = []
        for anchor in index.select("a[href]"):
            text = anchor.get_text(" ", strip=True)
            url = resolved_link(index_url, anchor.get("href", ""))
            if issue_pattern.fullmatch(urlsplit(url).path) and title_pattern.search(text):
                match = re.search(r"第\s*(\d+)\s*卷第\s*(\d+)\s*期", text)
                order = (int(match[1]), int(match[2])) if match else (0, 0)
                candidates.append((order, url))
        if not candidates:
            raise SourceError(f"No issue link matched the official PKU index: {self.journal['name']}")
        issue_url = max(candidates, key=lambda row: row[0])[1]
        if not within_hosts(issue_url, self.hosts):
            raise SourceError(f"Issue URL outside official hosts: {issue_url}")
        issue_html = fetch(issue_url, self.hosts, self.session)
        issue = BeautifulSoup(issue_html, "html.parser")
        published = None
        pub_meta = next((tag for tag in issue.select("meta[name][content]") if tag.get("name", "").casefold() == "pubdate"), None)
        if pub_meta:
            published = pub_meta.get("content")
        observations = []
        for anchor in issue.select("a[href]"):
            if anchor.get_text(" ", strip=True) != "全文下载":
                continue
            paragraph = anchor.find_parent("p")
            if not paragraph:
                continue
            title_soup = BeautifulSoup(str(paragraph), "html.parser")
            for trailing in title_soup.select("em"):
                trailing.decompose()
            title = title_soup.get_text(" ", strip=True)
            if len(title) < 4:
                continue
            article_url = resolved_link(issue_url, anchor.get("href", ""))
            if not within_hosts(article_url, self.hosts):
                raise SourceError(f"PKU article file outside official hosts: {article_url}")
            author_line = paragraph.find_next_sibling("p")
            author_text = author_line.get_text(" ", strip=True) if author_line else ""
            if not re.search(r"/\s*\d+\s*$", author_text):
                author_text = ""
            author_text = re.sub(r"/\s*\d+\s*$", "", author_text)
            author_text = re.sub(r"^[.…·\s]+", "", author_text)
            observations.append(self._observation(
                observed_at, title=title, article_url=article_url, visibility_url=issue_url,
                status=self.journal.get("label", "当期目录"), stable_id=url_key(article_url),
                authors=split_authors(author_text), published=published,
            ))
        if not observations:
            raise SourceError(f"No article downloads found on the latest official PKU issue: {self.journal['name']}")
        return ScanResult(self.source_id, self.journal["name"], "chinese_journal", observations, 2, "official PKU issue index and issue page")


def _find_text(node: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in node.iter():
        if child.tag.split("}")[-1].lower() in names and child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_feed(xml: str, source: dict, observed_at: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SourceError(f"Invalid RSS/Atom feed: {exc}") from exc
    entries = [n for n in root.iter() if n.tag.split("}")[-1] in {"item", "entry"}]
    if not entries:
        raise SourceError("Feed contains no item/entry records")
    result = []
    for entry in entries:
        title = _find_text(entry, ("title",))
        link = _find_text(entry, ("link",))
        if not link:
            link_node = next((n for n in entry if n.tag.split("}")[-1] == "link" and n.get("href")), None)
            link = link_node.get("href") if link_node is not None else None
        link = urljoin(source["feed_url"], link or "")
        if not title or not url_key(link):
            continue
        allowed_hosts = source.get("allowed_hosts") or [official_host(source["feed_url"])]
        if not within_hosts(link, allowed_hosts):
            raise SourceError(f"Feed entry leaves the verified source hosts: {link}")
        summary = _find_text(entry, ("description", "summary", "abstract"))
        if summary:
            summary = BeautifulSoup(summary, "html.parser").get_text(" ", strip=True)
        author = _find_text(entry, ("creator", "author", "name"))
        published = _find_text(entry, ("pubdate", "published", "updated", "date"))
        published_day = date_text(published)
        if not published_day and published:
            try:
                published_day = parsedate_to_datetime(published).date().isoformat()
            except (TypeError, ValueError, IndexError):
                pass
        result.append({
            "source_id": source["id"], "source_name": source["name"],
            "kind": "english_journal" if source["provider"] == "journal" else "working_paper",
            "language": "en", "journal": source["name"] if source["provider"] == "journal" else None,
            "priority": source.get("priority", "normal"), "title": title,
            "authors": split_authors(author), "doi": extract_doi(link + " " + (summary or "")),
            "stable_id": _find_text(entry, ("guid", "id")) or url_key(link),
            "official_url": link, "visibility_source_url": source["feed_url"],
            "status": source.get("status", "Working Paper" if source["provider"] != "journal" else "Published"),
            "published_online": published_day, "version_date": published,
            "abstract": summary, "observed_at": observed_at,
        })
    if not result:
        raise SourceError("Feed entries lack usable titles or official links")
    return result


class InternationalFeedSource:
    PROVIDER_HOSTS = {
        "nber": ["nber.org"], "cepr": ["cepr.org"],
        "repec": ["repec.org", "ideas.repec.org"], "ssrn": ["ssrn.com"],
    }

    def __init__(self, source: dict, session: requests.Session | None = None):
        self.source = dict(source)
        self.source.setdefault("id", source["provider"] + ":" + source["name"])
        self.session = session
        hosts = self.PROVIDER_HOSTS.get(source["provider"], [official_host(source["feed_url"])])
        if not within_hosts(source["feed_url"], hosts):
            raise ValueError(f"Feed is not on the configured provider's official host: {source['feed_url']}")
        self.hosts = hosts
        self.source["allowed_hosts"] = hosts if source["provider"] != "journal" else source.get("allowed_hosts") or hosts
        self.source_id = self.source["id"]

    def scan(self, observed_at: str) -> ScanResult:
        xml = fetch(self.source["feed_url"], self.hosts, self.session)
        items = parse_feed(xml, self.source, observed_at)
        kind = "english_journal" if self.source["provider"] == "journal" else "working_paper"
        return ScanResult(self.source_id, self.source["name"], kind, items, 1, "feed-snapshot")
