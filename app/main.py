"""FastAPI app: simple UI to create Jira tickets with optional AI drafting."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import (
    DEFAULT_JIRA_TEAM_NAME,
    load_client_jira_config,
    load_jira_config,
    load_suggest_config,
)
from .confluence_client import resolve_confluence_page
from .cursor_suggest import complete_bridge_suggest, draft_ticket_fields_cursor
from .jira_client import JiraError, create_issue, get_issue, search_sample_issues
from .llm_client import LlmError, draft_ticket_fields

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Jira issue key shape, e.g. ATL-25692
_PARENT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")

app = FastAPI(
    title="Jira Ticket UI",
    description="Minimal UI to create Jira tickets with AI-assisted drafting",
    version="1.3.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CreateTicketRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=32000)
    parent_key: str | None = Field(
        default=None,
        max_length=32,
        description="Parent epic/issue key; empty uses JIRA_PARENT_KEY env default",
    )
    team: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Atlassian Team friendly name or id for customfield_10001; "
            "empty omits the field"
        ),
    )


class CreateTicketResponse(BaseModel):
    success: bool
    key: str | None = None
    url: str | None = None
    error: str | None = None


class SuggestTicketRequest(BaseModel):
    intent: str = Field(..., min_length=1, max_length=8000)
    parent_key: str | None = Field(default=None, max_length=32)
    team: str | None = Field(default=None, max_length=128)
    wiki_page: str | None = Field(
        default=None,
        max_length=2000,
        description="Confluence page title or ma-banking wiki URL describing the problem",
    )
    client_ticket: str | None = Field(
        default=None,
        max_length=512,
        description="Client Jira issue key or browse URL",
    )


class SuggestTicketResponse(BaseModel):
    success: bool
    title: str | None = None
    description: str | None = None
    samples_used: int = 0
    parent_key: str | None = None
    provider: str | None = None
    wiki_title: str | None = None
    client_ticket_key: str | None = None
    error: str | None = None


class SuggestCompleteRequest(BaseModel):
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=32000)
    error: str | None = Field(default=None, max_length=2000)


@app.get("/")
def index() -> FileResponse:
    """Serve the ticket creation form."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    """Report whether required Jira/Suggest env config is present (no secrets)."""
    jira = load_jira_config()
    client_jira = load_client_jira_config()
    suggest = load_suggest_config()
    return {
        "ok": True,
        "jira_configured": jira.is_complete,
        "missing": jira.missing_keys(),
        "client_jira_site": client_jira.base_url or None,
        "client_jira_configured": bool(
            client_jira.base_url and client_jira.email and client_jira.api_token
        ),
        "project_key": jira.project_key or None,
        "issue_type": jira.issue_type,
        "parent_key": jira.parent_key or None,
        "team_name": jira.team_name or DEFAULT_JIRA_TEAM_NAME,
        "team_id": jira.team_id or None,
        "suggest_configured": suggest.is_complete,
        "suggest_provider": suggest.provider,
        "suggest_missing": suggest.missing_keys() if not suggest.is_complete else [],
        # Back-compat aliases for older UI checks
        "llm_configured": suggest.is_complete,
        "llm_provider": suggest.provider,
        "llm_missing": suggest.missing_keys() if not suggest.is_complete else [],
        "cursor_runtime": (
            suggest.cursor.runtime if suggest.provider == "cursor" else None
        ),
        "cursor_sdk_ready": bool(
            suggest.provider == "cursor" and suggest.cursor.api_key
        ),
        "cursor_bridge_ready": bool(
            suggest.provider == "cursor" and suggest.cursor.webhook_url
        ),
    }


@app.post("/api/suggest", response_model=SuggestTicketResponse)
async def suggest_ticket(body: SuggestTicketRequest) -> SuggestTicketResponse:
    """
    Draft title/description from user intent, inspired by tickets under parent.

    Default provider is Cursor (SDK). Does not create a Jira issue — the user
    must review and submit via ``POST /api/tickets``.
    """
    intent = body.intent.strip()
    if not intent:
        raise HTTPException(status_code=400, detail="Intent is required.")

    jira = load_jira_config()
    if not jira.is_complete:
        missing = ", ".join(jira.missing_keys())
        raise HTTPException(
            status_code=503,
            detail=(
                f"Jira is not configured. Set these environment variables "
                f"(see .env.example): {missing}"
            ),
        )

    suggest = load_suggest_config()
    if not suggest.is_complete:
        missing = ", ".join(suggest.missing_keys())
        raise HTTPException(
            status_code=503,
            detail=(
                f"Suggest is not configured. Set these environment variables "
                f"(see .env.example): {missing}"
            ),
        )

    parent_key = _resolve_parent_key(body.parent_key, jira.parent_key) or (
        jira.parent_key or ""
    )
    team = (body.team or "").strip() or jira.team_name

    try:
        samples = await asyncio.to_thread(search_sample_issues, jira, parent_key or None)
    except JiraError as exc:
        status = 502 if exc.status_code is None else min(exc.status_code, 599)
        if status < 400:
            status = 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    wiki_page = None
    wiki_ref = (body.wiki_page or "").strip()
    if wiki_ref:
        try:
            wiki_page = await asyncio.to_thread(resolve_confluence_page, jira, wiki_ref)
        except JiraError as exc:
            status = 502 if exc.status_code is None else min(exc.status_code, 599)
            if status < 400:
                status = 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    client_ticket = None
    client_ref = (body.client_ticket or "").strip()
    if client_ref:
        client_jira = load_client_jira_config()
        if not (client_jira.base_url and client_jira.email and client_jira.api_token):
            raise HTTPException(
                status_code=503,
                detail=(
                    "The customer Jira site is not configured. Set "
                    "CLIENT_JIRA_BASE_URL (and CLIENT_JIRA_EMAIL / "
                    "CLIENT_JIRA_API_TOKEN when they differ from the "
                    "development site); see .env.example."
                ),
            )
        try:
            client_ticket = await asyncio.to_thread(get_issue, client_jira, client_ref)
        except JiraError as exc:
            status = 502 if exc.status_code is None else min(exc.status_code, 599)
            if status < 400:
                status = 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    try:
        if suggest.provider == "cursor":
            draft = await asyncio.to_thread(
                draft_ticket_fields_cursor,
                suggest.cursor,
                intent=intent,
                samples=samples,
                parent_key=parent_key,
                team=team,
                wiki_page=wiki_page,
                client_ticket=client_ticket,
            )
        else:
            draft = await asyncio.to_thread(
                draft_ticket_fields,
                suggest.llm,
                intent=intent,
                samples=samples,
                parent_key=parent_key,
                wiki_page=wiki_page,
                client_ticket=client_ticket,
            )
    except LlmError as exc:
        status = 502 if exc.status_code is None else min(exc.status_code, 599)
        if status < 400:
            status = 502
        if exc.status_code in {401, 403}:
            status = 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return SuggestTicketResponse(
        success=True,
        title=draft["title"],
        description=draft["description"],
        samples_used=len(samples),
        parent_key=parent_key or None,
        provider=suggest.provider,
        wiki_title=(wiki_page or {}).get("title"),
        client_ticket_key=(client_ticket or {}).get("key"),
    )


@app.post("/api/suggest/{request_id}/complete")
def complete_suggest(
    request_id: str, body: SuggestCompleteRequest
) -> dict[str, object]:
    """
    Complete a Cursor Automations / file-bridge suggest job.

    Write ``title`` + ``description``, or ``error``, so a waiting
    ``POST /api/suggest`` (bridge mode) can finish.
    """
    try:
        path = complete_bridge_suggest(
            request_id,
            title=(body.title or "").strip(),
            description=(body.description or "").strip(),
            error=(body.error or "").strip() or None,
        )
    except LlmError as exc:
        status = exc.status_code or 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"success": True, "path": str(path)}


def _resolve_parent_key(requested: str | None, env_default: str) -> str | None:
    """
    Prefer the form/API parent key; fall back to env when empty.

    Returns None when neither provides a key. Raises HTTPException on bad format.
    """
    raw = (requested or "").strip()
    if not raw:
        raw = (env_default or "").strip()
    if not raw:
        return None
    if not _PARENT_KEY_RE.match(raw):
        raise HTTPException(
            status_code=400,
            detail=(
                "Parent issue must look like PROJECT-123 "
                "(letters/digits, hyphen, then digits)."
            ),
        )
    return raw.upper()


@app.post("/api/tickets", response_model=CreateTicketResponse)
def create_ticket(body: CreateTicketRequest) -> CreateTicketResponse:
    """Create a Jira issue from title and description (under parent when set)."""
    title = body.title.strip()
    description = body.description.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required.")

    config = load_jira_config()
    if not config.is_complete:
        missing = ", ".join(config.missing_keys())
        raise HTTPException(
            status_code=503,
            detail=(
                f"Jira is not configured. Set these environment variables "
                f"(see .env.example): {missing}"
            ),
        )

    parent_key = _resolve_parent_key(body.parent_key, config.parent_key)
    team = (body.team or "").strip() or None

    try:
        result = create_issue(
            config,
            title=title,
            description=description,
            parent_key=parent_key,
            team=team,
        )
    except JiraError as exc:
        status = 502 if exc.status_code is None else min(exc.status_code, 599)
        # Keep client-facing codes in 4xx/5xx that make sense for the UI
        if status < 400:
            status = 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return CreateTicketResponse(
        success=True,
        key=result["key"],
        url=result["url"],
    )
