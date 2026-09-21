"""Build and publish the cumulative table of discovered, summarized journal papers."""

from __future__ import annotations

import base64
import csv
import io
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests


TABLE_FILENAME = "discovered-and-summarized-papers.csv"
REPOSITORY_PATH = "reports/" + TABLE_FILENAME
HEADERS = ("论文题目", "来源期刊", "作者", "摘要")


class PaperTableError(RuntimeError):
    pass


def _configured_journal_sources(config: dict) -> tuple[set[str], set[str]]:
    source_ids = {
        "zh:" + journal["name"]
        for journal in config.get("chinese_monitor", {}).get("journals", [])
    }
    source_names = {
        journal["name"]
        for journal in config.get("chinese_monitor", {}).get("journals", [])
    }
    for source in config.get("international_monitor", {}).get("sources", []):
        if source.get("provider") in {"crossref", "journal"}:
            source_ids.add(source.get("id") or source["provider"] + ":" + source["name"])
            source_names.add(source["name"])
    return source_ids, source_names


def _plain(value: object) -> str:
    return " ".join(str(value or "").split())


def _csv_cell(value: object) -> str:
    text = _plain(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _overview(summary: dict) -> str | None:
    claim = next((item for item in summary.get("claims", [])
                  if item.get("field") == "overview" and item.get("text")), None)
    return _plain(claim["text"]) if claim else None


def summarized_paper_rows(state: dict, config: dict) -> list[dict[str, str]]:
    """Return one row for each summarized version from a configured journal."""
    allowed_ids, allowed_names = _configured_journal_sources(config)
    rows = []
    for work in state.get("works", {}).values():
        summary = work.get("summary") or {}
        if not summary.get("claims"):
            continue
        fingerprint = summary.get("version_fingerprint")
        event = next((item for item in work.get("versions", [])
                      if item.get("fingerprint") == fingerprint), None)
        if not event or event.get("kind") not in {"chinese_journal", "english_journal"}:
            continue
        if event.get("source_id") not in allowed_ids and event.get("source_name") not in allowed_names:
            continue
        abstract = _plain(event.get("abstract"))
        if not abstract:
            overview = _overview(summary)
            abstract = (
                "【来源未提供摘要；以下为系统提炼的内容概括】" + overview
                if overview else "来源未提供摘要，现有材料不足以形成内容概括。"
            )
        authors = event.get("authors") or work.get("authors") or []
        rows.append({
            "论文题目": _csv_cell(event.get("title") or work.get("title")),
            "来源期刊": _csv_cell(event.get("source_name") or work.get("journal")),
            "作者": _csv_cell("; ".join(_plain(author) for author in authors if _plain(author))),
            "摘要": _csv_cell(abstract),
            "_sort": str(work.get("first_discovered_at") or ""),
        })
    rows.sort(key=lambda row: (row["_sort"], row["论文题目"]), reverse=True)
    for row in rows:
        row.pop("_sort", None)
    return rows


def render_paper_table(state: dict, config: dict) -> tuple[str, int]:
    rows = summarized_paper_rows(state, config)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue(), len(rows)


def write_paper_table(state: dict, config: dict, destination: Path) -> int:
    content, count = render_paper_table(state, config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(destination)
    return count


class GitHubPaperTable:
    """Publish a generated report file to the default repository branch."""

    def __init__(self, *, branch: str = "main", path: str = REPOSITORY_PATH,
                 commit_message: str = "Update cumulative literature table [skip ci]"):
        self.repository = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.branch = branch
        self.path = path
        self.commit_message = commit_message
        parts = PurePosixPath(path).parts
        safe_path = parts and not path.startswith("/") and "\\" not in path and ":" not in path
        safe_path = safe_path and all(part not in {"", ".", ".."} for part in parts)
        safe_branch = re.fullmatch(r"[A-Za-z0-9._/-]+", branch or "") and ".." not in branch
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) or not self.token:
            raise PaperTableError("Repository token must be configured for paper-table publishing")
        if not safe_path or not safe_branch:
            raise PaperTableError("Invalid repository table path or branch")
        if not isinstance(commit_message, str) or not commit_message.strip() or "\n" in commit_message or "\r" in commit_message:
            raise PaperTableError("Invalid repository commit message")
        self.base = "https://api.github.com/repos/" + self.repository

    def _request(self, method: str, path: str, body: dict | None = None,
                 allow_missing: bool = False) -> dict | None:
        try:
            response = requests.request(
                method,
                self.base + path,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=body,
                timeout=35,
                allow_redirects=False,
            )
            if response.status_code == 404 and allow_missing:
                return None
            if not 200 <= response.status_code < 300:
                raise PaperTableError(f"Paper-table publishing failed with HTTP {response.status_code}")
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PaperTableError("Paper-table publishing connection or response failed") from exc

    def publish(self, source: Path) -> str:
        content = source.read_bytes()
        endpoint = "/contents/" + quote(self.path, safe="/")
        current = self._request("GET", endpoint + "?ref=" + quote(self.branch, safe=""), allow_missing=True)
        if current is not None:
            if not isinstance(current, dict) or not isinstance(current.get("sha"), str):
                raise PaperTableError("Unexpected existing paper-table response")
            encoded = current.get("content")
            if current.get("encoding") == "none":
                blob = self._request("GET", "/git/blobs/" + quote(current["sha"], safe=""))
                if not isinstance(blob, dict) or blob.get("encoding") != "base64":
                    raise PaperTableError("Unexpected existing paper-table blob response")
                encoded = blob.get("content")
            if not isinstance(encoded, str):
                raise PaperTableError("Existing paper table has no readable content")
            try:
                existing = base64.b64decode(encoded, validate=False)
            except (TypeError, ValueError) as exc:
                raise PaperTableError("Existing paper table has invalid encoding") from exc
            if existing == content:
                return "unchanged"
        body = {
            "message": self.commit_message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch,
        }
        if current is not None:
            body["sha"] = current["sha"]
        self._request("PUT", endpoint, body)
        return "updated" if current is not None else "created"
