"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


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
    """LLM provider settings (OpenAI or Azure OpenAI)."""

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
        if self.provider == "openai":
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
        return [
            "LLM_PROVIDER (or OPENAI_API_KEY / AZURE_OPENAI_API_KEY)",
        ]


def load_jira_config() -> JiraConfig:
    """Load Jira settings from environment (and optional .env file)."""
    raw_limit = (os.getenv("JIRA_SAMPLE_LIMIT") or "8").strip()
    try:
        sample_limit = max(1, min(20, int(raw_limit)))
    except ValueError:
        sample_limit = 8

    return JiraConfig(
        base_url=(os.getenv("JIRA_BASE_URL") or "").rstrip("/"),
        email=(os.getenv("JIRA_EMAIL") or "").strip(),
        api_token=(os.getenv("JIRA_API_TOKEN") or "").strip(),
        project_key=(os.getenv("JIRA_PROJECT_KEY") or "").strip(),
        issue_type=(os.getenv("JIRA_ISSUE_TYPE") or "Story").strip() or "Story",
        parent_key=(os.getenv("JIRA_PARENT_KEY") or "ATL-25692").strip(),
        sample_limit=sample_limit,
    )


def load_llm_config() -> LlmConfig:
    """
    Load LLM settings.

    Preference order when LLM_PROVIDER is unset:
    1. Azure OpenAI if AZURE_OPENAI_API_KEY is set
    2. OpenAI if OPENAI_API_KEY is set
    """
    azure_key = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()

    if explicit in {"azure", "openai"}:
        provider = explicit
    elif azure_key:
        provider = "azure"
    elif openai_key:
        provider = "openai"
    else:
        provider = ""

    api_key = azure_key if provider == "azure" else openai_key

    return LlmConfig(
        provider=provider,
        api_key=api_key,
        model=(os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini",
        azure_endpoint=(os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/"),
        azure_api_version=(
            os.getenv("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview"
        ).strip()
        or "2024-08-01-preview",
        azure_deployment=(os.getenv("AZURE_OPENAI_DEPLOYMENT") or "").strip(),
    )
