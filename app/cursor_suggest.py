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
    wiki_page: dict[str, str] | None = None,
    client_ticket: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Ask Cursor to draft title/description.

    Prefer Cloud Agents REST (``CURSOR_API_KEY``). If only the file/webhook
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
        wiki_page=wiki_page,
        client_ticket=client_ticket,
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
        wiki_page=wiki_page,
        client_ticket=client_ticket,
    )


def _draft_via_sdk(config: CursorSuggestConfig, *, prompt: str) -> dict[str, str]:
    """
    One-shot Cursor agent via Cloud Agents REST API.

    The Python ``cursor-sdk`` Bridge crashes on native Windows (WinError 10038),
    so Suggest uses ``https://api.cursor.com`` directly with the user API key.
    A no-repo cloud agent is enough: samples are already in the prompt.
    """
    return _draft_via_cloud_agents_api(config, prompt=prompt)


def _draft_via_cloud_agents_api(
    config: CursorSuggestConfig, *, prompt: str
) -> dict[str, str]:
    """Create a no-repo cloud agent, wait for the run, parse JSON draft."""
    auth = (config.api_key, "")
    create_url = "https://api.cursor.com/v1/agents"
    body: dict[str, Any] = {
        "prompt": {"text": prompt},
        "model": {"id": config.model or "composer-2.5"},
        "name": "edu-perso-jira-suggest",
    }

    try:
        # Create can take a while before headers return; allow a long read.
        create_response = httpx.post(
            create_url,
            auth=auth,
            json=body,
            timeout=httpx.Timeout(10.0, read=120.0),
        )
    except httpx.HTTPError as exc:
        raise LlmError(
            f"Could not reach Cursor Cloud Agents API: {exc}. "
            "Check network access to api.cursor.com and CURSOR_API_KEY."
        ) from exc

    if create_response.status_code >= 400:
        detail = create_response.text[:400].strip() or create_response.reason_phrase
        raise LlmError(
            f"Cursor Cloud Agents API rejected create ({create_response.status_code}): "
            f"{detail}"
        )

    try:
        payload = create_response.json()
    except json.JSONDecodeError as exc:
        raise LlmError("Cursor Cloud Agents API returned invalid JSON on create.") from exc

    agent = payload.get("agent") if isinstance(payload, dict) else None
    run = payload.get("run") if isinstance(payload, dict) else None
    if not isinstance(agent, dict) or not isinstance(run, dict):
        raise LlmError(
            "Cursor Cloud Agents API create response missing agent/run objects."
        )

    agent_id = str(agent.get("id") or "").strip()
    run_id = str(run.get("id") or "").strip()
    if not agent_id or not run_id:
        raise LlmError("Cursor Cloud Agents API create response missing agent/run id.")

    deadline = time.monotonic() + max(30, config.timeout_seconds)
    last_status = str(run.get("status") or "UNKNOWN")
    result_text = ""

    while time.monotonic() < deadline:
        try:
            run_response = httpx.get(
                f"https://api.cursor.com/v1/agents/{agent_id}/runs/{run_id}",
                auth=auth,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"Cursor run poll failed: {exc}") from exc

        if run_response.status_code >= 400:
            raise LlmError(
                f"Cursor run poll error ({run_response.status_code}): "
                f"{run_response.text[:300]}"
            )

        try:
            run_payload = run_response.json()
        except json.JSONDecodeError as exc:
            raise LlmError("Cursor run poll returned invalid JSON.") from exc

        last_status = str(run_payload.get("status") or last_status).upper()
        if last_status in {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}:
            raw_result = run_payload.get("result")
            if isinstance(raw_result, str):
                result_text = raw_result.strip()
            break
        time.sleep(2.0)
    else:
        raise LlmError(
            f"Timed out waiting for Cursor cloud agent run (last status: {last_status}). "
            f"See https://cursor.com/agents/{agent_id}"
        )

    if last_status != "FINISHED":
        raise LlmError(
            f"Cursor cloud agent run ended with status '{last_status}'. "
            f"See https://cursor.com/agents/{agent_id}"
        )

    if not result_text:
        # Fallback: conversation messages (v0) when run.result is empty.
        try:
            conversation = httpx.get(
                f"https://api.cursor.com/v0/agents/{agent_id}/conversation",
                auth=auth,
                timeout=30.0,
            )
            if conversation.status_code < 400:
                messages = conversation.json().get("messages") or []
                for message in reversed(messages):
                    if (
                        isinstance(message, dict)
                        and message.get("type") == "assistant_message"
                        and isinstance(message.get("text"), str)
                        and message["text"].strip()
                    ):
                        result_text = message["text"].strip()
                        break
        except (httpx.HTTPError, json.JSONDecodeError, TypeError, AttributeError):
            pass

    if not result_text:
        raise LlmError(
            "Cursor cloud agent finished but returned an empty result. "
            f"See https://cursor.com/agents/{agent_id}"
        )

    return _parse_draft_json(result_text)


def _draft_via_bridge(
    config: CursorSuggestConfig,
    *,
    intent: str,
    samples: list[dict[str, str]],
    parent_key: str,
    team: str,
    prompt: str,
    wiki_page: dict[str, str] | None = None,
    client_ticket: dict[str, str] | None = None,
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
        "wiki_page": wiki_page,
        "client_ticket": client_ticket,
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
