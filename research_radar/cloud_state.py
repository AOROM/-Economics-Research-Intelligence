"""Authenticated encrypted checkpoints in a separate GitHub state branch."""

from __future__ import annotations

import base64
import gzip
import json
import os
import re
from pathlib import Path, PurePosixPath

import requests


BRANCH = "research-radar-state"


class CloudStateError(RuntimeError):
    pass


def permitted_path(name: str) -> bool:
    parts = PurePosixPath(name).parts
    if not parts or any(p in {"..", "."} for p in parts) or name.startswith("/") or "\\" in name or ":" in name:
        return False
    return name in {"state.json", "delivery.json"} or bool(re.fullmatch(
        r"(?:summaries/[a-f0-9]+/[a-f0-9]+\.json|fulltexts/[a-f0-9]+\.json|emails/[A-Za-z0-9_-]+\.eml)", name))


def encrypt_state(workdir: Path, key: str) -> bytes:
    from cryptography.fernet import Fernet
    root = workdir.resolve()
    files = {}
    candidates = [workdir / "state.json", workdir / "delivery.json"]
    candidates += list((workdir / "summaries").rglob("*.json")) + list((workdir / "fulltexts").glob("*.json"))
    ledger_path = workdir / "delivery.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        if not isinstance(ledger, dict) or not isinstance(ledger.get("periods"), dict):
            raise CloudStateError("Invalid delivery ledger in runtime state")
        candidates += [workdir / row["message_file"] for row in ledger["periods"].values()
                       if isinstance(row, dict) and row.get("status") in {"pending", "transmitting", "uncertain"}
                       and row.get("message_file")]
    for path in candidates:
        try:
            resolved = path.resolve()
            name = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise CloudStateError("Runtime state path escaped the working directory") from exc
        if not permitted_path(name):
            raise CloudStateError("Unexpected runtime state path")
        if resolved.is_file():
            files[name] = resolved.read_bytes().decode("utf-8")
    if "state.json" not in files:
        raise CloudStateError("No research state available for checkpoint")
    raw = json.dumps({"schema_version": 1, "files": files}, ensure_ascii=False).encode("utf-8")
    if len(raw) > 100_000_000:
        raise CloudStateError("Runtime state exceeds the checkpoint size limit")
    try:
        return Fernet(key.encode("ascii")).encrypt(gzip.compress(raw))
    except (UnicodeError, ValueError) as exc:
        raise CloudStateError("Invalid encrypted-state key") from exc


def decrypt_state(ciphertext: bytes, workdir: Path, key: str) -> None:
    from cryptography.fernet import Fernet, InvalidToken
    try:
        raw = gzip.decompress(Fernet(key.encode("ascii")).decrypt(ciphertext))
        if len(raw) > 100_000_000:
            raise ValueError("state payload too large")
        payload = json.loads(raw)
    except (InvalidToken, UnicodeError, ValueError, OSError) as exc:
        raise CloudStateError("State could not be authenticated/decrypted; refusing to reset the baseline") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("files"), dict) or "state.json" not in payload["files"]:
        raise CloudStateError("Invalid encrypted state payload")
    destinations = []
    for name, content in payload["files"].items():
        if not permitted_path(name) or not isinstance(content, str):
            raise CloudStateError("Invalid file in encrypted state payload")
        destination = (workdir / name).resolve()
        if not destination.is_relative_to(workdir.resolve()):
            raise CloudStateError("State path escaped the working directory")
        destinations.append((destination, content))
    # Validate all paths before restoring any file.
    for destination, content in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        temp.write_bytes(content.encode("utf-8"))
        temp.replace(destination)


class GitHubState:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.repository = os.environ.get("GITHUB_REPOSITORY", "")
        self.token = os.environ.get("GITHUB_TOKEN", "")
        self.key = os.environ.get("RADAR_STATE_KEY", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) or not self.token or not self.key:
            raise CloudStateError("Repository token and encrypted-state key must be configured")
        self.base = "https://api.github.com/repos/" + self.repository
        self.head = None
        self.tree = None

    def _request(self, method: str, path: str, body: dict | None = None, allow_missing: bool = False) -> dict | None:
        try:
            response = requests.request(method, self.base + path,
                headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
                json=body, timeout=35, allow_redirects=False)
            if response.status_code == 404 and allow_missing:
                return None
            if not 200 <= response.status_code < 300:
                raise CloudStateError(f"State storage request failed with HTTP {response.status_code}")
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise CloudStateError("State storage connection or response failed") from exc

    def restore(self, initialize: bool = False) -> bool:
        ref = self._request("GET", "/git/ref/heads/" + BRANCH, allow_missing=True)
        if ref is None:
            if not initialize:
                raise CloudStateError("No saved state branch; initialize explicitly for the first run")
            return False
        try:
            self.head = ref["object"]["sha"]
            commit = self._request("GET", "/git/commits/" + self.head)
            self.tree = commit["tree"]["sha"]
            tree = self._request("GET", "/git/trees/" + self.tree)
            blob_sha = next((item["sha"] for item in tree["tree"] if item["path"] == "state.enc" and item["type"] == "blob"), None)
        except (KeyError, TypeError) as exc:
            raise CloudStateError("Invalid response while restoring encrypted state") from exc
        if not blob_sha:
            raise CloudStateError("State branch exists but has no encrypted checkpoint")
        blob = self._request("GET", "/git/blobs/" + blob_sha)
        if not isinstance(blob, dict) or blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
            raise CloudStateError("Unexpected checkpoint encoding")
        try:
            ciphertext = base64.b64decode(blob["content"], validate=False)
        except (ValueError, TypeError) as exc:
            raise CloudStateError("Invalid checkpoint encoding") from exc
        decrypt_state(ciphertext, self.workdir, self.key)
        return True

    def checkpoint(self) -> None:
        # Optimistic concurrency supplements the workflow's serialization.
        current = self._request("GET", "/git/ref/heads/" + BRANCH, allow_missing=True)
        if (current["object"]["sha"] if current else None) != self.head:
            raise CloudStateError("State changed in another run; refusing to overwrite it")
        cipher = encrypt_state(self.workdir, self.key)
        blob = self._request("POST", "/git/blobs", {"content": base64.b64encode(cipher).decode("ascii"), "encoding": "base64"})
        entries = [{"path": "state.enc", "mode": "100644", "type": "blob", "sha": blob["sha"]}]
        if not self.head:
            entries.append({"path": "README.md", "mode": "100644", "type": "blob", "content":
                "# Encrypted research radar runtime state\n\nThis branch holds authenticated encrypted checkpoints. The encryption key is stored separately as a repository secret. Do not edit state.enc manually.\n"})
        tree_body = {"tree": entries}
        if self.tree:
            tree_body["base_tree"] = self.tree
        tree = self._request("POST", "/git/trees", tree_body)
        commit = self._request("POST", "/git/commits", {"message": "Checkpoint encrypted research radar state",
                               "tree": tree["sha"], "parents": [self.head] if self.head else []})
        if self.head:
            self._request("PATCH", "/git/refs/heads/" + BRANCH, {"sha": commit["sha"], "force": False})
        else:
            self._request("POST", "/git/refs", {"ref": "refs/heads/" + BRANCH, "sha": commit["sha"]})
        self.head, self.tree = commit["sha"], tree["sha"]
