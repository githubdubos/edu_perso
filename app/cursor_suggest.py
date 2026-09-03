"""Draft Jira title/description via the Cursor agent (SDK or file/webhook bridge)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import CursorSuggestConfig
from .llm_client import LlmError, _parse_draft_json, build_draft_messages

# Repo-local inbox for the optional Automation / file bridge (not committed).
SUGGEST_DATA_DIR = Path(__file__).resolve().parent.parent / ".data" / "suggest"


def draft_ticket_fields_cursor(
    config: CursorSuggestConfig,
    *,
    intent: str,
    samples: list[dict[str, str]],
    parent_key: str,
    team: str = "",
) -> dict[str, str]:
    """
    Ask Cursor to draft title/description.

    Prefer the Cursor Python SDK (``CURSOR_API_KEY``). If only the file/webhook
    bridge is configured, write a request and wait for a response file (or a
    completion posted by an Automation).
    """
    if not config.is_complete:
        missing = ", ".join(config.missing_keys())
        raise LlmError(
            "Cursor suggest is not configured. Set these environment variables "
            f"(see .env.example): {missing}. "
            "Create an API key at https://cursor.com/dashboard/integrations "
            "or configure CURSOR_SUGGEST_WEBHOOK_URL + Automations (see README)."
        )

    system, user = build_draft_messages(
        intent=intent,
        samples=samples,
        parent_key=parent_key,
    )
    prompt = (
        f"{system}\n\n{user}\n\n"
        "Important: do not edit any repository files. Reply with ONLY the JSON "
        'object {"title": "...", "description": "..."}.'
    )

    if config.api_key:
        return _draft_via_sdk(config, prompt=prompt)

    return _draft_via_bridge(
        config,
        intent=intent,
        samples=samples,
        parent_key=parent_key,
        team=team,
        prompt=prompt,
    )


def _draft_via_sdk(config: CursorSuggestConfig, *, prompt: str) -> dict[str, str]:
    """One-shot Cursor agent run via cursor-sdk (local or cloud)."""
    try:
        from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, LocalAgentOptions
    except ImportError as exc:
        raise LlmError(
            "cursor-sdk is not installed. Run: pip install -r requirements.txt"
        ) from exc

    cwd = str(Path(__file__).resolve().parent.parent)
    options_kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": config.api_key,
    }

    if config.runtime == "cloud":
        # No-repo cloud agent: drafting only, no checkout required.
        options_kwargs["cloud"] = CloudAgentOptions(repos=[])
    else:
        # Local agent against this repo; disallow mutating tools.
        options_kwargs["local"] = LocalAgentOptions(cwd=cwd)
        # Drafting only — read-only tools; samples are already in the prompt.
        options_kwargs["tools"] = ["read", "grep", "glob", "ls"]

    try:
        result = Agent.prompt(prompt, AgentOptions(**options_kwargs))
    except Exception as exc:  # noqa: BLE001 — map SDK errors to LlmError
        message = str(getattr(exc, "message", None) or exc).strip()
        raise LlmError(
            f"Cursor agent error: {message[:500] or exc.__class__.__name__}. "
            "Check CURSOR_API_KEY and that the Cursor agent runtime can start."
        ) from exc

    status = getattr(result, "status", None)
    if status and status != "finished":
        raise LlmError(
            f"Cursor agent run ended with status '{status}'. "
            "Retry Suggest, or check Cursor usage / dashboard for the run."
        )

    content = getattr(result, "result", None)
    if not isinstance(content, str) or not content.strip():
        raise LlmError("Cursor agent returned an empty message.")
    return _parse_draft_json(content)


def _draft_via_bridge(
    config: CursorSuggestConfig,
    *,
    intent: str,
    samples: list[dict[str, str]],
    parent_key: str,
    team: str,
    prompt: str,
) -> dict[str, str]:
    """
    File + optional webhook bridge for Cursor Automations.

    1. Write ``.data/suggest/<id>.request.json``
    2. Optionally POST the payload to ``CURSOR_SUGGEST_WEBHOOK_URL``
    3. Poll for ``.data/suggest/<id>.response.json`` until timeout
    """
    SUGGEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request_path = SUGGEST_DATA_DIR / f"{request_id}.request.json"
    response_path = SUGGEST_DATA_DIR / f"{request_id}.response.json"

    payload = {
        "id": request_id,
        "intent": intent,
        "parent_key": parent_key,
        "team": team,
        "samples": samples,
        "prompt": prompt,
        "response_path": str(response_path),
        "complete_url_hint": f"POST /api/suggest/{request_id}/complete",
    }
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if config.webhook_url:
        try:
            httpx.post(config.webhook_url, json=payload, timeout=15.0)
        except httpx.RequestError as exc:
            raise LlmError(
                f"Could not reach CURSOR_SUGGEST_WEBHOOK_URL: {exc}. "
                "Check the Automation webhook URL in .env."
            ) from exc

    deadline = time.monotonic() + max(5, config.timeout_seconds)
    while time.monotonic() < deadline:
        if response_path.is_file():
            try:
                raw = response_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                raise LlmError(
                    f"Cursor bridge response file was invalid: {exc}"
                ) from exc
            if isinstance(data, dict) and data.get("error"):
                raise LlmError(str(data["error"])[:500])
            return _parse_draft_json(json.dumps(data) if isinstance(data, dict) else raw)
        time.sleep(1.0)

    raise LlmError(
        "Timed out waiting for Cursor Automations / bridge response. "
        f"Request written to {request_path}. "
        "Enable the Suggest automation (webhook) so an agent writes "
        f"{response_path.name}, or set CURSOR_API_KEY to use the Cursor SDK "
        "directly (see README)."
    )


def complete_bridge_suggest(
    request_id: str,
    *,
    title: str,
    description: str,
    error: str | None = None,
) -> Path:
    """Write a bridge response file (used by Automations or local agents)."""
    if not request_id or any(ch in request_id for ch in r"/\."):
        raise LlmError("Invalid suggest request id.", status_code=400)

    SUGGEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    response_path = SUGGEST_DATA_DIR / f"{request_id}.response.json"
    if error:
        body: dict[str, Any] = {"error": error}
    else:
        body = {"title": title, "description": description}
    response_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return response_path
