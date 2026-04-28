"""HTTP client for GitHub Gist export and import using stdlib only.

Rationale: keep network I/O for team sync out of the CLI module so hooks and
tests can reuse the same boundary without pulling Click into transport code.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import error, request

GITHUB_GISTS_API: str = "https://api.github.com/gists"
_USER_AGENT: str = "Cerebro-Memory/1.0 (urllib; local export/import)"


def http_json_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 90,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    """
    Perform a JSON-oriented HTTP request against the GitHub API.

    Uses urllib only; parses JSON bodies when valid, else returns raw str.
    Rationale: single choke point for Accept/User-Agent defaults on gist flows.

    Args:
        url: Request URL.
        method: HTTP method (default GET).
        data: Optional serialized request body.
        headers: Extra headers merged with defaults.
        timeout: Socket timeout seconds.

    Returns:
        tuple[int, dict[str, Any] | list[Any] | str]: HTTP status and parsed body.
    """
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", _USER_AGENT)
    hdrs.setdefault("Accept", "application/vnd.github+json")
    req = request.Request(url, data=data, headers=hdrs, method=method)
    with request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", 200) or 200)
        raw = resp.read().decode("utf-8")
    try:
        parsed: dict[str, Any] | list[Any] | str = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


def gist_id_from_gist_url(url: str) -> str | None:
    """
    Extract a gist id from a gist.github.com HTML URL.

    Args:
        url: User-facing gist URL.

    Returns:
        str | None: Hex-ish gist identifier if matched, else None.
    """
    m = re.search(r"gist\.github\.com/[^/]+/([0-9a-fA-F]{20,64})", url)
    return m.group(1) if m else None


def fetch_gist_markdown(gist_url: str) -> str:
    """
    Resolve a gist URL or API reference to raw markdown text.

    Supports gist.githubusercontent.com raw URLs and gist.github.com pages
    (via API + raw_url). Secret gists require GITHUB_TOKEN or GH_TOKEN.

    Args:
        gist_url: Raw URL or https://gist.github.com/<owner>/<id>/...

    Returns:
        str: File contents as UTF-8 text.

    Raises:
        ValueError: URL shape not recognized.
        RuntimeError: API response invalid or missing file metadata.
        urllib.error.HTTPError: Non-success HTTP from GitHub.
        urllib.error.URLError: Transport failure.
    """
    url = gist_url.strip()
    if "gist.githubusercontent.com" in url and "/raw/" in url:
        req = request.Request(url, headers={"User-Agent": _USER_AGENT})
        with request.urlopen(req, timeout=90) as resp:
            return resp.read().decode("utf-8")

    gist_id = gist_id_from_gist_url(url)
    if not gist_id:
        raise ValueError(
            "Unrecognized gist URL. Use https://gist.github.com/<owner>/<gist_id> "
            "or a gist.githubusercontent.com/.../raw/... URL."
        )

    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    headers: dict[str, str] = {"User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    api_url = f"{GITHUB_GISTS_API}/{gist_id}"
    try:
        _, parsed = http_json_request(api_url, method="GET", headers=headers)
    except error.HTTPError as exc:
        raise RuntimeError(
            "Could not fetch gist via API (secret gists often require GITHUB_TOKEN in env)."
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Unexpected GitHub API response shape.")

    files_obj = parsed.get("files")
    if not isinstance(files_obj, dict):
        raise RuntimeError("Gist response missing files.")

    chosen: dict[str, Any] | None = None
    if "KNOWLEDGE_GRAPH.md" in files_obj and isinstance(files_obj["KNOWLEDGE_GRAPH.md"], dict):
        chosen = files_obj["KNOWLEDGE_GRAPH.md"]
    else:
        for _fname, meta in files_obj.items():
            if isinstance(meta, dict):
                chosen = meta
                break
    if chosen is None:
        raise RuntimeError("Gist contains no readable file entries.")

    raw_url = str(chosen.get("raw_url") or "").strip()
    if not raw_url:
        raise RuntimeError("Gist file entry missing raw_url.")

    req = request.Request(raw_url, headers={"User-Agent": _USER_AGENT})
    with request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8")
