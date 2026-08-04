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


def load_jira_config() -> JiraConfig:
    """Load Jira settings from environment (and optional .env file)."""
    return JiraConfig(
        base_url=(os.getenv("JIRA_BASE_URL") or "").rstrip("/"),
        email=(os.getenv("JIRA_EMAIL") or "").strip(),
        api_token=(os.getenv("JIRA_API_TOKEN") or "").strip(),
        project_key=(os.getenv("JIRA_PROJECT_KEY") or "").strip(),
        issue_type=(os.getenv("JIRA_ISSUE_TYPE") or "Task").strip() or "Task",
    )
