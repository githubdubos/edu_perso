"""Minimal Jira Cloud/Server REST client for issue create and sample fetch."""

from __future__ import annotations

from typing import Any

import httpx

from .config import JiraConfig


class JiraError(Exception):
    """Raised when Jira rejects a request or returns an unexpected response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def plain_text_to_adf(text: str) -> dict[str, Any]:
    """Convert plain text to Atlassian Document Format (one paragraph per line)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    paragraphs: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            }
        )
    if not paragraphs:
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": " "}],
            }
        )
    return {"type": "doc", "version": 1, "content": paragraphs}


def adf_to_plain_text(node: Any) -> str:
    """Best-effort conversion of ADF (or string) description to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, dict):
        return str(node).strip()

    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            parts.append(item)
            return
        if not isinstance(item, dict):
            return
        node_type = item.get("type")
        if node_type == "text":
            parts.append(str(item.get("text") or ""))
            return
        if node_type == "hardBreak":
            parts.append("\n")
            return
        content = item.get("content")
        if isinstance(content, list):
            for child in content:
                walk(child)
            if node_type in {"paragraph", "heading", "bulletList", "orderedList", "listItem"}:
                parts.append("\n")

    walk(node)
    text = "".join(parts)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    # Collapse runs of blank lines
    cleaned: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            cleaned.append(line)
            blank = False
        elif not blank:
            cleaned.append("")
            blank = True
    return "\n".join(cleaned).strip()


def create_issue(
    config: JiraConfig,
    title: str,
    description: str,
    parent_key: str | None = None,
) -> dict[str, str]:
    """
    Create a Jira issue via REST API v3.

    Uses ``parent_key`` when provided; otherwise falls back to
    ``config.parent_key``. When set, the issue is linked as a child of that
    epic/parent (verified relationship for ATL-25692: ``parent`` field).

    Returns dict with keys: key, url, id.
    """
    resolved_parent = (parent_key if parent_key is not None else config.parent_key) or ""
    resolved_parent = resolved_parent.strip()

    fields: dict[str, Any] = {
        "project": {"key": config.project_key},
        "summary": title,
        "issuetype": {"name": config.issue_type},
        "description": plain_text_to_adf(description),
    }
    if resolved_parent:
        fields["parent"] = {"key": resolved_parent}

    payload = {"fields": fields}

    url = f"{config.base_url}/rest/api/3/issue"
    try:
        response = httpx.post(
            url,
            json=payload,
            auth=(config.email, config.api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise JiraError(f"Could not reach Jira at {config.base_url}: {exc}") from exc

    if response.status_code >= 400:
        detail = _format_jira_error(response)
        raise JiraError(detail, status_code=response.status_code)

    data = response.json()
    key = data.get("key")
    if not key:
        raise JiraError("Jira returned success but no issue key.")

    return {
        "key": key,
        "id": str(data.get("id", "")),
        "url": f"{config.base_url}/browse/{key}",
    }


def search_sample_issues(config: JiraConfig) -> list[dict[str, str]]:
    """
    Fetch recent sample issues under the configured parent epic.

    Uses JQL ``parent = <JIRA_PARENT_KEY>`` (children of ATL-25692 use the
    parent field, not a separate Epic Link custom field on this site).
    """
    if not config.parent_key:
        raise JiraError("JIRA_PARENT_KEY is not configured.")

    jql = f"parent = {config.parent_key} ORDER BY updated DESC"
    fields = [
        "summary",
        "description",
        "issuetype",
        "labels",
        "components",
        "priority",
    ]
    auth = (config.email, config.api_token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    # Prefer enhanced search (POST /search/jql); fall back to classic GET /search.
    url = f"{config.base_url}/rest/api/3/search/jql"
    try:
        response = httpx.post(
            url,
            json={
                "jql": jql,
                "maxResults": config.sample_limit,
                "fields": fields,
            },
            auth=auth,
            headers=headers,
            timeout=30.0,
        )
    except httpx.RequestError as exc:
        raise JiraError(f"Could not reach Jira at {config.base_url}: {exc}") from exc

    if response.status_code in {404, 405}:
        url = f"{config.base_url}/rest/api/3/search"
        try:
            response = httpx.get(
                url,
                params={
                    "jql": jql,
                    "maxResults": config.sample_limit,
                    "fields": ",".join(fields),
                },
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise JiraError(f"Could not reach Jira at {config.base_url}: {exc}") from exc

    if response.status_code >= 400:
        detail = _format_jira_error(response)
        raise JiraError(detail, status_code=response.status_code)

    data = response.json()
    issues = data.get("issues") or []
    samples: list[dict[str, str]] = []
    for issue in issues:
        fields = issue.get("fields") or {}
        issuetype = fields.get("issuetype") or {}
        labels = fields.get("labels") or []
        components = fields.get("components") or []
        priority = fields.get("priority") or {}
        samples.append(
            {
                "key": str(issue.get("key") or ""),
                "summary": str(fields.get("summary") or ""),
                "description": adf_to_plain_text(fields.get("description")),
                "issuetype": str(issuetype.get("name") or ""),
                "labels": ", ".join(str(label) for label in labels),
                "components": ", ".join(
                    str(component.get("name") or "")
                    for component in components
                    if isinstance(component, dict)
                ),
                "priority": str(priority.get("name") or ""),
            }
        )
    return samples


def _format_jira_error(response: httpx.Response) -> str:
    """Build a readable error message from a Jira error response."""
    try:
        body = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return f"Jira API error ({response.status_code}): {text or 'no details'}"

    messages: list[str] = []
    if isinstance(body.get("errorMessages"), list):
        messages.extend(str(m) for m in body["errorMessages"])
    errors = body.get("errors")
    if isinstance(errors, dict):
        for field, msg in errors.items():
            messages.append(f"{field}: {msg}")
    if not messages:
        messages.append(str(body))
    return f"Jira API error ({response.status_code}): " + "; ".join(messages)
