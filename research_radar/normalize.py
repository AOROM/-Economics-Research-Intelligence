"""Stable identifiers and conservative text normalization."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def text_key(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value or "")).casefold()
    return " ".join(re.findall(r"[\w\u4e00-\u9fff]+", value))


def doi_key(value: str | None) -> str | None:
    if not value:
        return None
    value = html.unescape(value).strip()
    value = re.sub(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", "", value, flags=re.I)
    value = value.split("?", 1)[0].split("#", 1)[0].strip().rstrip(".,;:)]}").lower()
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def url_key(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, query, ""))


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]


def extract_doi(value: str | None) -> str | None:
    match = re.search(r"10\.\d{4,9}/[^\s<>\"']+", value or "", re.I)
    return doi_key(match.group(0)) if match else None
