"""Version-bound source passages for paper summaries; no new discovery sources."""

from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .normalize import stable_hash, url_key


def plain_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup.select("script, style, noscript"):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def sentences(value: str) -> list[str]:
    # Decimal points are not sentence boundaries; Chinese needs no space.
    return [s.strip() for s in re.split(r"(?<=[。！？])|(?<=[.!?])\s+(?=[A-Z\u3400-\u9fff])", value) if s.strip()]


def _blocks(text: str, prefix: str, location: str, url: str) -> list[dict]:
    parts = []
    for sentence in sentences(text):
        # Bound very long paragraphs while keeping exact, contiguous passages.
        parts.extend(sentence[i:i + 1800] for i in range(0, len(sentence), 1800))
    return [{"id": f"{prefix}:{i}", "text": part, "location": f"{location}，第 {i} 段", "url": url}
            for i, part in enumerate(parts, 1)]


def import_fulltext(path: Path, work: dict, workdir: Path, source_url: str | None = None) -> Path:
    """Import user-supplied UTF-8 text/Markdown or a text PDF for this version."""
    if path.stat().st_size > 25_000_000:
        raise ValueError("Full text exceeds the 25 MB import limit")
    event = work["versions"][-1]
    source_url = source_url or event["official_url"]
    if not url_key(source_url):
        raise ValueError("Full text requires an HTTP(S) source URL")
    pages = []
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError('PDF import requires: pip install -e ".[pdf]"') from exc
        try:
            reader = PdfReader(path)
            if len(reader.pages) > 500:
                raise ValueError("PDF exceeds the 500-page import limit")
            pages = [{"page": i, "text": page.extract_text() or ""} for i, page in enumerate(reader.pages, 1)]
        except Exception as exc:
            raise ValueError("PDF could not be read; supply a readable text file") from exc
    elif path.suffix.lower() in {".txt", ".md"}:
        pages = [{"page": None, "text": path.read_text(encoding="utf-8-sig")}]
    else:
        raise ValueError("Full text import accepts .pdf, .txt or .md")
    if sum(len(page["text"].strip()) for page in pages) < 100:
        raise ValueError("No usable body text; scanned PDFs need OCR before import")
    record = {"schema_version": 1, "version_fingerprint": event["fingerprint"],
              "source_url": source_url, "origin": "user-provided", "pages": pages,
              "partial": any(not page["text"].strip() for page in pages)}
    destination = workdir / "fulltexts" / (work["canonical_work_id"] + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(destination)
    return destination


def build_document(work: dict, workdir: Path, max_chars: int = 30000) -> dict:
    event = work["versions"][-1]
    url = event["official_url"]
    blocks = [{"id": "title:1", "text": plain_text(event.get("title") or work["title"]),
               "location": "标题", "url": url}]
    abstract = plain_text(event.get("abstract") or "")
    blocks += _blocks(abstract, "abstract", "摘要", url)
    scope = "title-and-abstract" if abstract else "title-only"
    notes = []
    fulltext = workdir / "fulltexts" / (work["canonical_work_id"] + ".json")
    if fulltext.exists():
        try:
            body = json.loads(fulltext.read_text(encoding="utf-8"))
            if body["version_fingerprint"] != event["fingerprint"]:
                notes.append("已保存正文属于另一论文版本，本次未使用。")
            else:
                if not url_key(body["source_url"]) or not isinstance(body["pages"], list):
                    raise ValueError("Invalid full text record")
                imported = []
                for i, page in enumerate(body["pages"], 1):
                    if not isinstance(page, dict) or not isinstance(page.get("text"), str):
                        raise ValueError("Invalid full text page")
                    location = f"正文第 {page['page']} 页" if page.get("page") else "提供的正文"
                    text = " ".join(page["text"].split())
                    imported += _blocks(text, f"body-{i}", location, body["source_url"])
                if not imported:
                    raise ValueError("Empty full text record")
                blocks += imported
                scope = "provided-full-text-partial" if body.get("partial") else "provided-full-text"
                notes.append("正文由用户提供；段落位置对应导入文本，PDF 页码为文件页序。")
        except (OSError, ValueError, KeyError, TypeError):
            notes.append("正文文件无法解析，本次使用可用的标题和摘要。")
    total = len(blocks)
    # Preserve title/abstract first, then spread the remaining budget across the
    # body, giving findings/conclusions priority over references/introduction.
    head = [b for b in blocks if not b["id"].startswith("body-")]
    body_blocks = [b for b in blocks if b["id"].startswith("body-")]
    priority = re.compile(r"研究发现|结果表明|结果显示|结论|不显著|未发现|we find|we show|conclusion|results|no significant", re.I)
    candidates = head + sorted(body_blocks, key=lambda b: not bool(priority.search(b["text"])))
    selected, used = [], 0
    for block in candidates:
        if used + len(block["text"]) <= max_chars:
            selected.append(block)
            used += len(block["text"])
    selected_ids = {b["id"] for b in selected}
    selected = [b for b in blocks if b["id"] in selected_ids]
    if len(selected) < total:
        scope = "provided-full-text-partial" if "full-text" in scope else "abstract-excerpt"
        notes.append(f"本次使用 {len(selected)}/{total} 个原文段落；其余段落未进入提炼。")
    content_hash = stable_hash(json.dumps(blocks, ensure_ascii=False, sort_keys=True), scope,
                               json.dumps([b["id"] for b in selected]), json.dumps(notes, ensure_ascii=False))
    return {"version_fingerprint": event["fingerprint"], "content_hash": content_hash,
            "scope": scope, "blocks": selected, "notes": notes, "total_blocks": total}
