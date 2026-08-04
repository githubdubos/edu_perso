"""Minimal OpenAI / Azure OpenAI / Gemini chat client for ticket drafting."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import LlmConfig


class LlmError(Exception):
    """Raised when the LLM provider rejects a request or returns bad data."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def draft_ticket_fields(
    config: LlmConfig,
    *,
    intent: str,
    samples: list[dict[str, str]],
    parent_key: str,
) -> dict[str, str]:
    """
    Ask the LLM to draft title and description matching sample ticket style.

    Returns dict with keys: title, description.
    """
    if not config.is_complete:
        missing = ", ".join(config.missing_keys())
        raise LlmError(
            f"LLM is not configured. Set these environment variables "
            f"(see .env.example): {missing}"
        )

    system = (
        "You draft Jira tickets. Match the style, title prefixes, tone, and "
        "level of technical detail of the sample tickets. Reply with ONLY a "
        "JSON object with keys \"title\" and \"description\" (plain text, no "
        "markdown fences). Do not invent unrelated products; stay faithful to "
        "the user's intent while sounding like the samples."
    )
    sample_blocks: list[str] = []
    for index, sample in enumerate(samples, start=1):
        sample_blocks.append(
            "\n".join(
                [
                    f"### Sample {index} ({sample.get('key') or 'unknown'})",
                    f"Type: {sample.get('issuetype') or 'n/a'}",
                    f"Priority: {sample.get('priority') or 'n/a'}",
                    f"Labels: {sample.get('labels') or 'none'}",
                    f"Components: {sample.get('components') or 'none'}",
                    f"Title: {sample.get('summary') or ''}",
                    "Description:",
                    (sample.get("description") or "(empty)")[:2500],
                ]
            )
        )

    user = (
        f"Parent epic/key for context: {parent_key or 'none'}\n\n"
        f"User intent / sketch:\n{intent.strip()}\n\n"
        "Reference tickets (match their patterns):\n\n"
        + ("\n\n".join(sample_blocks) if sample_blocks else "(no samples available)")
        + "\n\nReturn JSON: {\"title\": \"...\", \"description\": \"...\"}"
    )

    if config.provider == "gemini":
        content = _gemini_completion(config, system=system, user=user)
    else:
        content = _openai_compatible_completion(config, system=system, user=user)
    return _parse_draft_json(content)


def _gemini_completion(config: LlmConfig, *, system: str, user: str) -> str:
    """Call Gemini Developer API (google-genai) and return model text."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise LlmError(
            "google-genai is not installed. Run: pip install -r requirements.txt"
        ) from exc

    try:
        client = genai.Client(api_key=config.api_key)
        response = client.models.generate_content(
            model=config.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
                response_mime_type="application/json",
            ),
        )
    except Exception as exc:  # noqa: BLE001 — map SDK/provider errors
        message = str(exc).strip() or exc.__class__.__name__
        # Avoid echoing long payloads; never include the API key.
        raise LlmError(f"Gemini API error: {message[:400]}") from exc

    content = getattr(response, "text", None)
    if not isinstance(content, str) or not content.strip():
        raise LlmError("LLM provider returned an empty message.")
    return content.strip()


def _openai_compatible_completion(
    config: LlmConfig, *, system: str, user: str
) -> str:
    """Call OpenAI-compatible chat completions and return assistant text."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if config.provider == "azure":
        url = (
            f"{config.azure_endpoint}/openai/deployments/"
            f"{config.azure_deployment}/chat/completions"
            f"?api-version={config.azure_api_version}"
        )
        headers = {
            "api-key": config.api_key,
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": 0.4,
        }
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }

    try:
        response = httpx.post(url, headers=headers, json=body, timeout=60.0)
    except httpx.RequestError as exc:
        raise LlmError(f"Could not reach LLM provider: {exc}") from exc

    if response.status_code >= 400:
        # Never echo API keys; keep provider error text only.
        detail = _safe_provider_error(response)
        raise LlmError(detail, status_code=response.status_code)

    try:
        data = response.json()
    except ValueError as exc:
        raise LlmError("LLM provider returned non-JSON response.") from exc

    choices = data.get("choices") or []
    if not choices:
        raise LlmError("LLM provider returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LlmError("LLM provider returned an empty message.")
    return content.strip()


def _parse_draft_json(content: str) -> dict[str, str]:
    """Extract title/description from model output."""
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: find first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LlmError("LLM response was not valid JSON.") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LlmError("LLM response was not valid JSON.") from exc

    if not isinstance(data, dict):
        raise LlmError("LLM JSON must be an object with title and description.")

    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    if not title:
        raise LlmError("LLM did not return a title.")
    if len(title) > 255:
        title = title[:255].rstrip()
    return {"title": title, "description": description}


def _safe_provider_error(response: httpx.Response) -> str:
    """Format provider errors without leaking secrets."""
    try:
        body = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return f"LLM API error ({response.status_code}): {text[:400] or 'no details'}"

    error = body.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or str(error)
        return f"LLM API error ({response.status_code}): {message}"
    if isinstance(error, str):
        return f"LLM API error ({response.status_code}): {error}"
    return f"LLM API error ({response.status_code}): {str(body)[:400]}"
