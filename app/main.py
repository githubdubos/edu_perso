"""FastAPI app: simple UI to create Jira tickets with optional AI drafting."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_jira_config, load_llm_config
from .jira_client import JiraError, create_issue, search_sample_issues
from .llm_client import LlmError, draft_ticket_fields

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Jira Ticket UI",
    description="Minimal UI to create Jira tickets with AI-assisted drafting",
    version="1.1.0",
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CreateTicketRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=32000)


class CreateTicketResponse(BaseModel):
    success: bool
    key: str | None = None
    url: str | None = None
    error: str | None = None


class SuggestTicketRequest(BaseModel):
    intent: str = Field(..., min_length=1, max_length=8000)


class SuggestTicketResponse(BaseModel):
    success: bool
    title: str | None = None
    description: str | None = None
    samples_used: int = 0
    parent_key: str | None = None
    error: str | None = None


@app.get("/")
def index() -> FileResponse:
    """Serve the ticket creation form."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    """Report whether required Jira/LLM env config is present (no secrets)."""
    jira = load_jira_config()
    llm = load_llm_config()
    return {
        "ok": True,
        "jira_configured": jira.is_complete,
        "missing": jira.missing_keys(),
        "project_key": jira.project_key or None,
        "issue_type": jira.issue_type,
        "parent_key": jira.parent_key or None,
        "llm_configured": llm.is_complete,
        "llm_provider": llm.provider or None,
        "llm_missing": llm.missing_keys() if not llm.is_complete else [],
    }


@app.post("/api/suggest", response_model=SuggestTicketResponse)
def suggest_ticket(body: SuggestTicketRequest) -> SuggestTicketResponse:
    """
    Draft title/description from user intent, inspired by tickets under parent.

    Does not create a Jira issue — the user must review and submit via
    ``POST /api/tickets``.
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

    llm = load_llm_config()
    if not llm.is_complete:
        missing = ", ".join(llm.missing_keys())
        raise HTTPException(
            status_code=503,
            detail=(
                f"LLM is not configured. Set these environment variables "
                f"(see .env.example): {missing}"
            ),
        )

    try:
        samples = search_sample_issues(jira)
    except JiraError as exc:
        status = 502 if exc.status_code is None else min(exc.status_code, 599)
        if status < 400:
            status = 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    try:
        draft = draft_ticket_fields(
            llm,
            intent=intent,
            samples=samples,
            parent_key=jira.parent_key,
        )
    except LlmError as exc:
        status = 502 if exc.status_code is None else min(exc.status_code, 599)
        if status < 400:
            status = 502
        if exc.status_code == 401 or exc.status_code == 403:
            status = 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return SuggestTicketResponse(
        success=True,
        title=draft["title"],
        description=draft["description"],
        samples_used=len(samples),
        parent_key=jira.parent_key or None,
    )


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

    try:
        result = create_issue(config, title=title, description=description)
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
