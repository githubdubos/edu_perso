"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from pathlib import Path

from dotenv import load_dotenv

# Always load the project .env (override empty shell vars so Suggest sees CURSOR_API_KEY).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

# Default Atlassian Team shown in the UI (name) and sent as customfield_10001 (id).
# Verified from epic ATL-25692 on ma-banking.atlassian.net.
DEFAULT_JIRA_TEAM_NAME = "BC.RCOFit+LR"
DEFAULT_JIRA_TEAM_ID = "7ed41a1b-0081-46cd-b045-228ee9e6d8b4-7"

# Default Suggest provider: Cursor agent (SDK). Gemini/OpenAI remain optional.
DEFAULT_SUGGEST_PROVIDER = "cursor"

# Atlassian site holding customer tickets, distinct from the development site.
DEFAULT_CLIENT_JIRA_BASE_URL = "https://regnology-cloud.atlassian.net"


@dataclass(frozen=True)
class JiraConfig:
    """Jira connection settings from environment."""

    base_url: str
    email: str
    api_token: str
    project_key: str
    issue_type: str
    parent_key: str
    sample_limit: int
    team_name: str
    team_id: str

    @property
    def is_complete(self) -> bool:
        return all(
            [
                self.base_url,
                self.email,
                self.api_token,
                self.project_key,
            ]
        )

    def missing_keys(self) -> list[str]:
        required = {
            "JIRA_BASE_URL": self.base_url,
            "JIRA_EMAIL": self.email,
            "JIRA_API_TOKEN": self.api_token,
            "JIRA_PROJECT_KEY": self.project_key,
        }
        return [key for key, value in required.items() if not value]


@dataclass(frozen=True)
class LlmConfig:
    """LLM provider settings (OpenAI, Azure OpenAI, or Gemini)."""

    provider: str
    api_key: str
    model: str
    azure_endpoint: str
    azure_api_version: str
    azure_deployment: str

    @property
    def is_complete(self) -> bool:
        if self.provider == "azure":
            return bool(
                self.api_key
                and self.azure_endpoint
                and self.azure_deployment
            )
        if self.provider in {"openai", "gemini"}:
            return bool(self.api_key and self.model)
        return False

    def missing_keys(self) -> list[str]:
        if self.provider == "azure":
            required = {
                "AZURE_OPENAI_API_KEY": self.api_key,
                "AZURE_OPENAI_ENDPOINT": self.azure_endpoint,
                "AZURE_OPENAI_DEPLOYMENT": self.azure_deployment,
            }
            return [key for key, value in required.items() if not value]
        if self.provider == "openai":
            required = {
                "OPENAI_API_KEY": self.api_key,
                "OPENAI_MODEL": self.model,
            }
            return [key for key, value in required.items() if not value]
        if self.provider == "gemini":
            missing: list[str] = []
            if not self.api_key:
                missing.append("GEMINI_API_KEY (or GOOGLE_API_KEY)")
            if not self.model:
                missing.append("GEMINI_MODEL")
            return missing
        return [
            "LLM_PROVIDER (or OPENAI_API_KEY / AZURE_OPENAI_API_KEY / "
            "GEMINI_API_KEY)",
        ]


@dataclass(frozen=True)
class CursorSuggestConfig:
    """Cursor agent settings for Suggest (SDK and/or Automation bridge)."""

    api_key: str
    model: str
    runtime: str
    webhook_url: str
    timeout_seconds: int

    @property
    def is_complete(self) -> bool:
        # SDK path (preferred) or webhook/file bridge without an API key.
        return bool(self.api_key) or bool(self.webhook_url)

    def missing_keys(self) -> list[str]:
        if self.is_complete:
            return []
        return [
            "CURSOR_API_KEY (preferred) or CURSOR_SUGGEST_WEBHOOK_URL "
            "(Automations bridge)",
        ]


@dataclass(frozen=True)
class SuggestConfig:
    """Which backend powers the Suggest button."""

    provider: str
    cursor: CursorSuggestConfig
    llm: LlmConfig

    @property
    def is_complete(self) -> bool:
        if self.provider == "cursor":
            return self.cursor.is_complete
        return self.llm.is_complete

    def missing_keys(self) -> list[str]:
        if self.provider == "cursor":
            return self.cursor.missing_keys()
        return self.llm.missing_keys()


def load_jira_config() -> JiraConfig:
    """Load Jira settings from environment (and optional .env file)."""
    raw_limit = (os.getenv("JIRA_SAMPLE_LIMIT") or "8").strip()
    try:
        sample_limit = max(1, min(20, int(raw_limit)))
    except ValueError:
        sample_limit = 8

    team_name = (os.getenv("JIRA_TEAM_NAME") or DEFAULT_JIRA_TEAM_NAME).strip()
    team_id = (os.getenv("JIRA_TEAM_ID") or "").strip()
    if not team_id and team_name == DEFAULT_JIRA_TEAM_NAME:
        team_id = DEFAULT_JIRA_TEAM_ID

    return JiraConfig(
        base_url=(os.getenv("JIRA_BASE_URL") or "").rstrip("/"),
        email=(os.getenv("JIRA_EMAIL") or "").strip(),
        api_token=(os.getenv("JIRA_API_TOKEN") or "").strip(),
        project_key=(os.getenv("JIRA_PROJECT_KEY") or "ATL").strip() or "ATL",
        issue_type=(os.getenv("JIRA_ISSUE_TYPE") or "Story").strip() or "Story",
        parent_key=(os.getenv("JIRA_PARENT_KEY") or "ATL-25692").strip(),
        sample_limit=sample_limit,
        team_name=team_name,
        team_id=team_id,
    )


def load_client_jira_config() -> JiraConfig:
    """
    Load the Jira site that holds customer tickets.

    Customer tickets live on a different Atlassian site than the development
    project, so the "Client ticket reference" field must be resolved there.
    Atlassian API tokens are account-scoped rather than site-scoped, so the
    development credentials work here unless overridden.
    """
    base_url = (
        os.getenv("CLIENT_JIRA_BASE_URL") or DEFAULT_CLIENT_JIRA_BASE_URL
    ).rstrip("/")
    email = (os.getenv("CLIENT_JIRA_EMAIL") or os.getenv("JIRA_EMAIL") or "").strip()
    api_token = (
        os.getenv("CLIENT_JIRA_API_TOKEN") or os.getenv("JIRA_API_TOKEN") or ""
    ).strip()

    return JiraConfig(
        base_url=base_url,
        email=email,
        api_token=api_token,
        # Read-only site: creation settings below are never used.
        project_key="",
        issue_type="",
        parent_key="",
        sample_limit=1,
        team_name="",
        team_id="",
    )


def load_llm_config() -> LlmConfig:
    """
    Load classic LLM settings (Gemini / OpenAI / Azure).

    Preference order when LLM_PROVIDER is unset:
    1. Azure OpenAI if AZURE_OPENAI_API_KEY is set
    2. OpenAI if OPENAI_API_KEY is set
    3. Gemini if GEMINI_API_KEY or GOOGLE_API_KEY is set
    """
    azure_key = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    gemini_key = (
        (os.getenv("GEMINI_API_KEY") or "").strip()
        or (os.getenv("GOOGLE_API_KEY") or "").strip()
    )
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()

    if explicit in {"azure", "openai", "gemini"}:
        provider = explicit
    elif azure_key:
        provider = "azure"
    elif openai_key:
        provider = "openai"
    elif gemini_key:
        provider = "gemini"
    else:
        provider = ""

    if provider == "azure":
        api_key = azure_key
        model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"
    elif provider == "gemini":
        api_key = gemini_key
        model = (
            (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
            or "gemini-2.0-flash"
        )
    else:
        api_key = openai_key
        model = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"

    return LlmConfig(
        provider=provider,
        api_key=api_key,
        model=model,
        azure_endpoint=(os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/"),
        azure_api_version=(
            os.getenv("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview"
        ).strip()
        or "2024-08-01-preview",
        azure_deployment=(os.getenv("AZURE_OPENAI_DEPLOYMENT") or "").strip(),
    )


def load_cursor_suggest_config() -> CursorSuggestConfig:
    """Load Cursor SDK / Automations bridge settings for Suggest."""
    raw_timeout = (os.getenv("CURSOR_SUGGEST_TIMEOUT_SECONDS") or "120").strip()
    try:
        timeout_seconds = max(15, min(600, int(raw_timeout)))
    except ValueError:
        timeout_seconds = 120

    runtime = (os.getenv("CURSOR_RUNTIME") or "local").strip().lower()
    if runtime not in {"local", "cloud"}:
        runtime = "local"

    return CursorSuggestConfig(
        api_key=(os.getenv("CURSOR_API_KEY") or "").strip(),
        model=(os.getenv("CURSOR_MODEL") or "composer-2.5").strip() or "composer-2.5",
        runtime=runtime,
        webhook_url=(os.getenv("CURSOR_SUGGEST_WEBHOOK_URL") or "").strip(),
        timeout_seconds=timeout_seconds,
    )


def load_suggest_config() -> SuggestConfig:
    """
    Resolve Suggest backend.

    ``SUGGEST_PROVIDER`` wins when set (``cursor`` | ``gemini`` | ``openai`` |
    ``azure``). Default is ``cursor``. Classic ``LLM_PROVIDER`` still selects
    the Gemini/OpenAI/Azure credentials when Suggest uses those backends.
    """
    explicit = (os.getenv("SUGGEST_PROVIDER") or "").strip().lower()
    llm = load_llm_config()
    cursor = load_cursor_suggest_config()

    if explicit in {"cursor", "gemini", "openai", "azure"}:
        provider = explicit
    else:
        provider = DEFAULT_SUGGEST_PROVIDER

    # When Suggest targets a classic LLM, reuse LLM_PROVIDER / keys.
    if provider in {"gemini", "openai", "azure"} and llm.provider != provider:
        # Force the requested provider; keys still come from env via load_llm_config
        # fields — rebuild a shallow copy with the explicit provider name.
        llm = LlmConfig(
            provider=provider,
            api_key=(
                (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
                if provider == "gemini"
                else (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
                if provider == "azure"
                else (os.getenv("OPENAI_API_KEY") or "").strip()
            ),
            model=(
                (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
                or "gemini-2.0-flash"
                if provider == "gemini"
                else (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
                or "gpt-4o-mini"
            ),
            azure_endpoint=(os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/"),
            azure_api_version=(
                os.getenv("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview"
            ).strip()
            or "2024-08-01-preview",
            azure_deployment=(os.getenv("AZURE_OPENAI_DEPLOYMENT") or "").strip(),
        )

    return SuggestConfig(provider=provider, cursor=cursor, llm=llm)
