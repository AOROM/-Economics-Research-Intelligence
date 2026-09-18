"""Configuration loading and source safety checks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml


PROVIDERS = {"nber", "cepr", "repec", "ssrn", "journal"}


def official_host(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"HTTPS official URL required: {url}")
    return parts.hostname.lower()


def within_hosts(url: str, hosts: list[str]) -> bool:
    try:
        host = official_host(url)
    except ValueError:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in hosts)


def load_config(path: str | Path) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Configuration must be a mapping")
    if not raw.get("monitor_id") or not raw.get("topic", {}).get("statement"):
        raise ValueError("monitor_id and topic.statement are required")
    chinese = raw.get("chinese_monitor") or {}
    if chinese.get("official_site_only") is not True or chinese.get("auto_expand_journals") is not False or chinese.get("allow_database_discovery") is not False:
        raise ValueError("Chinese monitoring must use the explicit official-site whitelist")
    names = set()
    for journal in chinese.get("journals", []):
        name = journal.get("name")
        if not name or name in names:
            raise ValueError("Chinese journal names must be present and unique")
        names.add(name)
        homepage_host = official_host(journal["homepage"])
        hosts = journal.get("allowed_hosts") or [homepage_host]
        if homepage_host not in hosts:
            raise ValueError(f"Homepage host missing from allowed_hosts: {name}")
        for surface in journal.get("surfaces", []):
            if not within_hosts(surface["url"], hosts):
                raise ValueError(f"Surface is outside the official hosts: {name}")
            for field in ("item_selector", "title_selector", "link_selector"):
                if not surface.get(field):
                    raise ValueError(f"{name} surface requires {field}")
        if not journal.get("surfaces"):
            raise ValueError(f"Chinese journal requires at least one official surface: {name}")
    source_ids = set()
    for source in raw.get("international_monitor", {}).get("sources", []):
        if source.get("provider") not in PROVIDERS or not source.get("name"):
            raise ValueError("International source requires a known provider and name")
        source_id = source.get("id") or source["provider"] + ":" + source["name"]
        if source_id in source_ids:
            raise ValueError(f"Duplicate international source id: {source_id}")
        source_ids.add(source_id)
        official_host(source["feed_url"])
    return raw
