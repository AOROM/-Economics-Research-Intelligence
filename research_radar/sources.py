"""Official Chinese journal pages and explicitly configured international feeds."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

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


def fetch(url: str, hosts: list[str], session: requests.Session | None = None) -> str:
    if not within_hosts(url, hosts):
        raise SourceError(f"URL outside configured official hosts: {url}")
    session = session or requests.Session()
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=20, headers={"User-Agent": "EconomicsResearchRadar/0.1 (research monitoring)"})
            if not within_hosts(response.url, hosts):
                raise SourceError(f"Redirect outside configured official hosts: {response.url}")
            response.raise_for_status()
            if len(response.content) > 5_000_000:
                raise SourceError("Response exceeds 5 MB limit")
            return response.text
        except (requests.RequestException, SourceError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise SourceError(f"Official source failed: {url}: {last_error}")


def selected_text(node, selector: str | None) -> str | None:
    if not selector:
        return None
    found = node.select_one(selector)
    return found.get_text(" ", strip=True) if found else None


def selected_link(node, selector: str | None, base: str) -> str | None:
    found = node.select_one(selector) if selector else None
    return urljoin(base, found.get("href", "")) if found and found.get("href") else None


def split_authors(value: str | None) -> list[str]:
    return [v.strip() for v in re.split(r"\s*(?:,|，|;|；|、|\band\b|和)\s*", value or "") if v.strip()]


def date_text(value: str | None) -> str | None:
    match = re.search(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})", value or "")
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


class ChineseOfficialSource:
    def __init__(self, journal: dict, session: requests.Session | None = None):
        self.journal = journal
        self.session = session
        self.hosts = journal.get("allowed_hosts") or [official_host(journal["homepage"])]
        self.source_id = "zh:" + journal["name"]

    def scan(self, observed_at: str) -> ScanResult:
        observations: list[dict] = []
        pages = 0
        for surface in self.journal["surfaces"]:
            current = surface["url"]
            visited: set[str] = set()
            max_pages = int(surface.get("max_pages", 20))
            while current:
                key = url_key(current)
                if key in visited:
                    raise SourceError(f"Pagination loop on {self.journal['name']}: {current}")
                if len(visited) >= max_pages:
                    raise SourceError("Configured pagination limit reached")
                visited.add(key or current)
                soup = BeautifulSoup(fetch(current, self.hosts, self.session), "html.parser")
                pages += 1
                for item in soup.select(surface["item_selector"]):
                    title = selected_text(item, surface["title_selector"])
                    article_url = selected_link(item, surface["link_selector"], current)
                    if not title or not article_url:
                        continue
                    if not within_hosts(article_url, self.hosts):
                        raise SourceError(f"Article URL outside official hosts: {article_url}")
                    detail = surface.get("article") or {}
                    article_html = fetch(article_url, self.hosts, self.session) if detail else None
                    article = BeautifulSoup(article_html, "html.parser") if article_html else None
                    abstract = selected_text(article, detail.get("abstract_selector")) if article else None
                    doi = extract_doi(selected_text(item, surface.get("doi_selector")))
                    if not doi and article:
                        doi = extract_doi(selected_text(article, detail.get("doi_selector")) or article_html)
                    authors = selected_text(item, surface.get("author_selector")) or (selected_text(article, detail.get("author_selector")) if article else None)
                    date = selected_text(item, surface.get("date_selector")) or (selected_text(article, detail.get("date_selector")) if article else None)
                    observations.append({
                        "source_id": self.source_id, "source_name": self.journal["name"],
                        "kind": "chinese_journal", "language": "zh", "journal": self.journal["name"],
                        "priority": self.journal.get("priority", "normal"), "title": title,
                        "authors": split_authors(authors), "doi": doi,
                        "stable_id": item.get("data-article-id") or item.get("id") or url_key(article_url),
                        "official_url": article_url, "visibility_source_url": current,
                        "status": surface["label"], "published_online": date_text(date),
                        "abstract": abstract, "observed_at": observed_at,
                    })
                next_selector = surface.get("next_selector")
                next_node = soup.select_one(next_selector) if next_selector else None
                next_url = urljoin(current, next_node.get("href", "")) if next_node and next_node.get("href") else None
                if next_node and not next_url:
                    raise SourceError(f"Dynamic pagination requires a custom adapter: {current}")
                if next_url and not within_hosts(next_url, self.hosts):
                    raise SourceError(f"Pagination left official hosts: {next_url}")
                if next_url and len(visited) >= max_pages:
                    raise SourceError(f"Pagination exceeded max_pages={max_pages}: {current}")
                current = next_url
        return ScanResult(self.source_id, self.journal["name"], "chinese_journal", observations, pages, "official-surface")


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
