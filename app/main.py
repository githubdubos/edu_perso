"""FastAPI app: simple UI to create Jira tickets."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_jira_config
from .jira_client import JiraError, create_issue

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Jira Ticket UI",
    description="Minimal UI to create Jira tickets",
    version="1.0.0",
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


@app.get("/")
def index() -> FileResponse:
    """Serve the ticket creation form."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, object]:
    """Report whether required Jira env config is present (no secrets)."""
    config = load_jira_config()
    return {
        "ok": True,
        "jira_configured": config.is_complete,
        "missing": config.missing_keys(),
        "project_key": config.project_key or None,
        "issue_type": config.issue_type,
    }


@app.post("/api/tickets", response_model=CreateTicketResponse)
def create_ticket(body: CreateTicketRequest) -> CreateTicketResponse:
    """Create a Jira issue from title and description."""
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
