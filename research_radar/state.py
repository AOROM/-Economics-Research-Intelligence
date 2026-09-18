"""Persistent ResearchWork identity, version events, and atomic state writes."""

from __future__ import annotations

import copy
import json
from difflib import SequenceMatcher
from pathlib import Path

from .analyzer import analyze
from .normalize import doi_key, stable_hash, text_key, url_key


def empty_state(monitor_id: str) -> dict:
    return {"schema_version": 1, "monitor_id": monitor_id, "works": {}, "source_scans": {}}


def load_state(path: str | Path, monitor_id: str) -> dict:
    path = Path(path)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_state(monitor_id)
    if state.get("schema_version") != 1 or state.get("monitor_id") != monitor_id:
        raise ValueError("State schema or monitor_id mismatch")
    return state


def save_json_atomic(path: str | Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _author_keys(authors: list[str]) -> set[str]:
    return {text_key(author) for author in authors if text_key(author)}


def _candidate_score(observation: dict, work: dict) -> float:
    title_a, title_b = text_key(observation.get("title")), text_key(work.get("title"))
    if not title_a or not title_b:
        return 0
    similarity = SequenceMatcher(None, title_a, title_b).ratio()
    authors_a, authors_b = _author_keys(observation.get("authors") or []), _author_keys(work.get("authors") or [])
    overlap = len(authors_a & authors_b) / max(len(authors_a), len(authors_b), 1)
    same_journal = observation.get("journal") and observation.get("journal") == work.get("journal")
    if observation.get("kind") == "chinese_journal" and not same_journal:
        return 0
    if not authors_a or not authors_b:
        # A matching title without authors may suggest a lineage, but is never
        # strong enough for automatic merging.
        return 0.8 * similarity
    return 0.7 * similarity + 0.3 * overlap


def find_work(works: dict[str, dict], observation: dict) -> tuple[str | None, list[str]]:
    doi = doi_key(observation.get("doi"))
    stable = str(observation.get("source_id")) + ":" + str(observation.get("stable_id"))
    url = url_key(observation.get("official_url"))
    direct = []
    for work_id, work in works.items():
        for event in work.get("versions", []):
            if doi and doi == doi_key(event.get("doi")):
                direct.append(work_id)
                break
            if stable == event.get("source_stable_key") or (url and url == url_key(event.get("official_url"))):
                direct.append(work_id)
                break
    direct = sorted(set(direct))
    if len(direct) == 1:
        return direct[0], []
    if len(direct) > 1:
        return None, direct
    scores = sorted(((_candidate_score(observation, work), work_id) for work_id, work in works.items()), reverse=True)
    strong = [work_id for score, work_id in scores if score >= 0.96]
    if len(strong) == 1:
        return strong[0], []
    return None, [work_id for score, work_id in scores if score >= 0.78][:5]


def _version_fingerprint(observation: dict) -> str:
    return stable_hash(
        str(observation.get("source_id")), str(observation.get("stable_id")),
        str(observation.get("status")), str(observation.get("version_date") or observation.get("published_online")),
        str(observation.get("abstract") or ""), str(doi_key(observation.get("doi")) or ""),
        str(url_key(observation.get("official_url")) or ""),
    )


def apply_observations(state: dict, scans: list, topic: dict, observed_at: str) -> tuple[dict, dict]:
    """Apply complete scans in memory. Caller writes the digest before persisting state."""
    updated = copy.deepcopy(state)
    changes = {"new": [], "updated": [], "baseline": [], "possible_links": []}
    for scan in scans:
        prior = updated["source_scans"].get(scan.source_id)
        baseline = not prior or not prior.get("last_successful_scan_at")
        for obs in scan.observations:
            work_id, possible = find_work(updated["works"], obs)
            if not work_id:
                work_id = stable_hash(obs["source_id"], str(obs.get("stable_id") or obs["official_url"]))
                while work_id in updated["works"]:
                    work_id = stable_hash(work_id, obs["title"])
                updated["works"][work_id] = {
                    "canonical_work_id": work_id, "title": obs["title"],
                    "authors": obs.get("authors") or [], "language": obs.get("language"),
                    "journal": obs.get("journal"), "first_discovered_at": observed_at,
                    "first_public_version_at": None, "current_version_at": None,
                    "journal_publication_at": None,
                    "versions": [], "analysis": {}, "possible_links": possible,
                }
                if possible:
                    changes["possible_links"].append({"work_id": work_id, "candidates": possible})
                kind = "baseline" if baseline else "new"
            else:
                kind = "baseline" if baseline else "updated"
            work = updated["works"][work_id]
            fingerprint = _version_fingerprint(obs)
            if any(event["fingerprint"] == fingerprint for event in work["versions"]):
                continue
            event = {
                "fingerprint": fingerprint, "source_id": obs["source_id"],
                "source_name": obs["source_name"], "source_stable_key": obs["source_id"] + ":" + str(obs.get("stable_id")),
                "kind": obs["kind"], "status": obs.get("status"), "doi": doi_key(obs.get("doi")),
                "official_url": obs["official_url"], "visibility_source_url": obs["visibility_source_url"],
                "first_seen_at": observed_at, "published_online": obs.get("published_online"),
                "version_date": obs.get("version_date"), "abstract": obs.get("abstract"),
                "priority": obs.get("priority", "normal"), "baseline": baseline,
            }
            work["versions"].append(event)
            official_day = obs.get("published_online")
            if official_day:
                first = work.get("first_public_version_at")
                current = work.get("current_version_at")
                work["first_public_version_at"] = min(first, official_day) if first else official_day
                work["current_version_at"] = max(current, official_day) if current else official_day
                if obs["kind"] in {"chinese_journal", "english_journal"} and obs.get("status", "").lower() in {"正式出版", "正式发表", "published"}:
                    work["journal_publication_at"] = official_day
            if not work.get("authors") and obs.get("authors"):
                work["authors"] = obs["authors"]
            if obs.get("status", "").lower() in {"正式出版", "正式发表", "published"}:
                work["title"] = obs["title"]
            work["analysis"] = analyze(obs, topic)
            changes[kind].append({"work_id": work_id, "work": work, "event": event, "change_type": kind})
        updated["source_scans"][scan.source_id] = {
            "source_name": scan.source_name, "kind": scan.kind,
            "last_successful_scan_at": observed_at, "candidate_count": len(scan.observations),
            "pages": scan.pages, "coverage": scan.coverage,
        }
    return updated, changes


def research_map(state: dict) -> dict:
    concepts: dict[str, dict] = {}
    for work_id, work in state["works"].items():
        analysis = work.get("analysis") or {}
        for concept in analysis.get("concepts", {}):
            entry = concepts.setdefault(concept, {"works": [], "methods": {}, "datasets": {}})
            entry["works"].append(work_id)
            for method in analysis.get("methods", []):
                entry["methods"][method] = entry["methods"].get(method, 0) + 1
            for dataset in analysis.get("datasets", []):
                entry["datasets"][dataset] = entry["datasets"].get(dataset, 0) + 1
    return {"schema_version": 1, "concepts": concepts, "note": "Observed works only; absence is not evidence of a research gap."}
