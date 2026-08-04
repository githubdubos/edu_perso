"""Minimal Jira Cloud/Server REST client for issue creation."""

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


def create_issue(config: JiraConfig, title: str, description: str) -> dict[str, str]:
    """
    Create a Jira issue via REST API v3.

    Returns dict with keys: key, url, id.
    """
    payload = {
        "fields": {
            "project": {"key": config.project_key},
            "summary": title,
            "issuetype": {"name": config.issue_type},
            "description": plain_text_to_adf(description),
        }
    }

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
