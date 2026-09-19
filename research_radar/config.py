"""Configuration loading and source safety checks."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml


PROVIDERS = {"nber", "cepr", "repec", "ssrn", "journal"}
CHINESE_ADAPTERS = {"html", "ajcass_api", "pku_issue"}


def summary_options(raw: dict) -> dict:
    options = {"mode": "extractive", "max_model_calls": 20, "max_attempts": 3,
               "max_input_chars": 30000, "max_output_tokens": 4000, "timeout_seconds": 45,
               "api_key_env": "RESEARCH_RADAR_API_KEY"}
    supplied = raw.get("summarization", {})
    if not isinstance(supplied, dict):
        raise ValueError("summarization must be a mapping")
    options.update(supplied)
    if options["mode"] not in {"extractive", "model"}:
        raise ValueError("summarization.mode must be extractive or model")
    for name, low, high in [("max_model_calls", 0, 1000), ("max_attempts", 1, 10),
                            ("max_input_chars", 2000, 200000), ("max_output_tokens", 500, 16000),
                            ("timeout_seconds", 1, 120)]:
        value = options[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"summarization.{name} must be an integer in [{low}, {high}]")
    if options["mode"] == "model":
        if not isinstance(options.get("endpoint"), str):
            raise ValueError("summarization.endpoint must be a URL string")
        endpoint = urlsplit(options["endpoint"])
        local = endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        if not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
            raise ValueError("Model endpoint must be a URL without credentials, query or fragment")
        if endpoint.scheme != "https" and not (local and endpoint.scheme == "http"):
            raise ValueError("Model endpoint requires HTTPS (HTTP is allowed for loopback servers)")
        if not isinstance(options.get("model"), str) or not options["model"].strip():
            raise ValueError("summarization.model is required in model mode")
        if not isinstance(options.get("api_key_env"), str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", options["api_key_env"]):
            raise ValueError("summarization.api_key_env must name an environment variable")
    return options


def validate_email(raw: dict) -> None:
    email = raw.get("email", {})
    if not isinstance(email, dict):
        raise ValueError("email must be a mapping")
    for name in ("subject_prefix", "from", "to", "greeting", "signature"):
        value = email.get(name, "")
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise ValueError(f"email.{name} must be a single-line string")


def official_host(url: str, allow_http: bool = False) -> str:
    parts = urlsplit(url)
    schemes = {"https", "http"} if allow_http else {"https"}
    if parts.scheme not in schemes or not parts.hostname:
        requirement = "HTTP(S)" if allow_http else "HTTPS"
        raise ValueError(f"{requirement} official URL required: {url}")
    return parts.hostname.lower()


def within_hosts(url: str, hosts: list[str], allow_http: bool = False) -> bool:
    try:
        host = official_host(url, allow_http=allow_http)
    except ValueError:
        return False
    return any(host == allowed.lower() or host.endswith("." + allowed.lower()) for allowed in hosts)


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
        status = journal.get("status", "active")
        if status not in {"active", "pending", "blocked"}:
            raise ValueError(f"Unknown Chinese journal status: {name}")
        if status in {"pending", "blocked"}:
            if journal.get("surfaces"):
                raise ValueError(f"Inactive journal cannot have active surfaces: {name}")
            homepage = urlsplit(journal.get("homepage") or "")
            if homepage.scheme not in {"http", "https"} or not homepage.hostname:
                raise ValueError(f"Inactive journal requires a homepage: {name}")
            if status == "blocked" and not journal.get("note"):
                raise ValueError(f"Blocked journal requires an evidence note: {name}")
            continue
        allow_http = journal.get("allow_http") is True
        homepage_host = official_host(journal["homepage"], allow_http=allow_http)
        hosts = journal.get("allowed_hosts") or [homepage_host]
        if homepage_host not in hosts:
            raise ValueError(f"Homepage host missing from allowed_hosts: {name}")
        adapter = journal.get("adapter", "html")
        if adapter not in CHINESE_ADAPTERS:
            raise ValueError(f"Unknown Chinese journal adapter for {name}: {adapter}")
        if adapter == "ajcass_api":
            if not journal.get("journal_id") or not journal.get("api_url") or not journal.get("detail_url_template"):
                raise ValueError(f"AJCASS adapter requires journal_id, api_url and detail_url_template: {name}")
            api_host = official_host(journal["api_url"])
            if api_host not in hosts or not within_hosts(journal["api_url"], hosts):
                raise ValueError(f"AJCASS API host missing from allowed_hosts: {name}")
            continue
        if adapter == "pku_issue":
            issue_index = journal.get("issue_index_url")
            if not issue_index or not within_hosts(issue_index, hosts, allow_http=allow_http):
                raise ValueError(f"PKU issue adapter requires an official issue_index_url: {name}")
            if not journal.get("issue_link_regex"):
                raise ValueError(f"PKU issue adapter requires issue_link_regex: {name}")
            try:
                re.compile(journal["issue_link_regex"])
            except re.error as exc:
                raise ValueError(f"Invalid issue URL pattern for {name}: {exc}") from exc
            continue
        for surface in journal.get("surfaces", []):
            if not within_hosts(surface["url"], hosts, allow_http=allow_http):
                raise ValueError(f"Surface is outside the official hosts: {name}")
            if surface.get("link_path_regex"):
                try:
                    re.compile(surface["link_path_regex"])
                except re.error as exc:
                    raise ValueError(f"Invalid article URL pattern for {name}: {exc}") from exc
            else:
                for field in ("item_selector", "title_selector", "link_selector"):
                    if not surface.get(field):
                        raise ValueError(f"{name} surface requires {field} or link_path_regex")
        if adapter == "html" and not journal.get("surfaces"):
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
    summary_options(raw)
    validate_email(raw)
    return raw
