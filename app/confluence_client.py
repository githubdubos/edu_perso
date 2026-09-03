"""Fetch Confluence Cloud page content using the same Atlassian credentials as Jira."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .config import JiraConfig
from .jira_client import JiraError

# https://ma-banking.atlassian.net/wiki/spaces/ERFS/pages/442106176/Title
_PAGE_URL_RE = re.compile(
    r"/wiki/spaces/[^/]+/pages/(\d+)(?:/|$)",
    re.IGNORECASE,
)
# Tiny links: /wiki/x/Fc1bBw
_TINY_URL_RE = re.compile(r"/wiki/x/([A-Za-z0-9_-]+)(?:/|$)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def resolve_confluence_page(config: JiraConfig, page_ref: str) -> dict[str, str]:
    """
    Resolve a wiki page name or URL and return title + plain-text body.

    Accepts:
    - Full Confluence URL with ``/pages/<id>/...``
    - Numeric page id
    - Page title (CQL title search on the site)
    """
    raw = (page_ref or "").strip()
    if not raw:
        raise JiraError("Wiki page is empty.", status_code=400)

    page_id = _extract_page_id(raw)
    if page_id:
        return _fetch_page_by_id(config, page_id)

    # Title search (prefer exact title match).
    return _fetch_page_by_title(config, raw)


def _extract_page_id(raw: str) -> str | None:
    if re.fullmatch(r"\d+", raw):
        return raw
    if "://" not in raw and not raw.lower().startswith("wiki/"):
        return None
    match = _PAGE_URL_RE.search(raw)
    if match:
        return match.group(1)
    tiny = _TINY_URL_RE.search(raw)
    if tiny:
        # Caller will resolve via content API using tiny id as pageId where supported.
        return tiny.group(1)
    parsed = urlparse(raw if "://" in raw else f"https://dummy/{raw}")
    # Last path segment numeric?
    parts = [p for p in parsed.path.split("/") if p]
    for part in reversed(parts):
        if part.isdigit():
            return part
    return None


def _wiki_base(config: JiraConfig) -> str:
    return f"{config.base_url.rstrip('/')}/wiki"


def _auth_headers(config: JiraConfig) -> tuple[tuple[str, str], dict[str, str]]:
    return (config.email, config.api_token), {"Accept": "application/json"}


def _fetch_page_by_id(config: JiraConfig, page_id: str) -> dict[str, str]:
    url = f"{_wiki_base(config)}/rest/api/content/{page_id}"
    auth, headers = _auth_headers(config)
    try:
        response = httpx.get(
            url,
            params={"expand": "body.storage,space"},
            auth=auth,
            headers=headers,
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise JiraError(f"Could not reach Confluence: {exc}") from exc

    if response.status_code >= 400:
        if response.status_code == 403:
            raise JiraError(
                "Confluence access denied for this Atlassian API token. "
                "On ma-banking.atlassian.net, grant Confluence product access to "
                f"{config.email}, then recreate the API token if needed.",
                status_code=403,
            )
        raise JiraError(
            _format_confluence_error(response),
            status_code=response.status_code,
        )
    return _page_payload(response.json(), config.base_url)


def _fetch_page_by_title(config: JiraConfig, title: str) -> dict[str, str]:
    # Escape double quotes in CQL string literal.
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    cql = f'type=page AND title="{safe_title}"'
    url = f"{_wiki_base(config)}/rest/api/content/search"
    auth, headers = _auth_headers(config)
    try:
        response = httpx.get(
            url,
            params={"cql": cql, "limit": 5, "expand": "body.storage,space"},
            auth=auth,
            headers=headers,
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise JiraError(f"Could not reach Confluence: {exc}") from exc

    if response.status_code >= 400:
        # Fallback: title~ fuzzy search
        cql_fuzzy = f'type=page AND title~"{safe_title}"'
        try:
            response = httpx.get(
                url,
                params={"cql": cql_fuzzy, "limit": 5, "expand": "body.storage,space"},
                auth=auth,
                headers=headers,
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise JiraError(f"Could not reach Confluence: {exc}") from exc
        if response.status_code >= 400:
            raise JiraError(
                _format_confluence_error(response),
                status_code=response.status_code,
            )

    data = response.json()
    results = data.get("results") or []
    if not results:
        raise JiraError(
            f"No Confluence page found for '{title}'. "
            "Paste the full page URL or an exact page title.",
            status_code=404,
        )

    # Prefer exact title match (case-insensitive).
    chosen = results[0]
    for item in results:
        if str(item.get("title") or "").casefold() == title.casefold():
            chosen = item
            break
    return _page_payload(chosen, config.base_url)


def _page_payload(data: dict[str, Any], site_base: str) -> dict[str, str]:
    title = str(data.get("title") or "").strip() or "(untitled)"
    page_id = str(data.get("id") or "")
    space = (data.get("space") or {}).get("key") or ""
    body = ((data.get("body") or {}).get("storage") or {}).get("value") or ""
    text = storage_html_to_plain_text(str(body))
    if len(text) > 12000:
        text = text[:12000].rstrip() + "\n… [truncated]"

    links = data.get("_links") or {}
    webui = str(links.get("webui") or "")
    url = ""
    if webui:
        url = f"{site_base.rstrip('/')}/wiki{webui}"
    elif space and page_id:
        slug = unquote(title).replace(" ", "+")
        url = f"{site_base.rstrip('/')}/wiki/spaces/{space}/pages/{page_id}/{slug}"

    return {
        "id": page_id,
        "title": title,
        "space": str(space),
        "url": url,
        "body": text,
    }


def storage_html_to_plain_text(value: str) -> str:
    """Rough conversion of Confluence storage HTML to plain text."""
    if not value:
        return ""
    text = value
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n", text)
    text = re.sub(r"(?i)</li>", "\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line:
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip()


def _format_confluence_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return (
            f"Confluence API error ({response.status_code}): "
            f"{text[:400] or 'no details'}"
        )
    message = body.get("message") or body.get("errorMessage") or str(body)
    return f"Confluence API error ({response.status_code}): {str(message)[:400]}"
