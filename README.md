# edu_perso

Personal education / sandbox project.

## Cursor rules

Agent guidance for this repository is versioned under [`.cursor/rules/`](.cursor/rules/).

Conventions enforced for contributors and agents:

- **English** for code, comments, documentation, and commit messages
- **Documentation** stays in sync when behavior or setup changes
- **Dedicated branches** — do not develop directly on `main`
- **Commit and push** when a feature or fix is done, or before switching topics

See [`.cursor/rules/README.md`](.cursor/rules/README.md) for the full list and how to add rules.

## Jira Ticket UI

Small FastAPI web app to create Jira issues from a simple form (title + description). Inspired by patterns from `configops-mcp-server` (REST create issue + env-based Atlassian credentials), kept minimal for this sandbox.

### Features

- Title and description inputs
- Submit creates a Jira issue via REST API v3
- Success / failure feedback
- On success: link to the new ticket and cleared form fields

### Setup

1. Create a virtualenv and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy env template and fill in real values (do not commit `.env`):

```powershell
copy .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_BASE_URL` | yes | Jira base URL, e.g. `https://your-domain.atlassian.net` |
| `JIRA_EMAIL` | yes | Atlassian account email |
| `JIRA_API_TOKEN` | yes | [Atlassian API token](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_PROJECT_KEY` | yes | Target project key (e.g. `PROJ`) |
| `JIRA_ISSUE_TYPE` | no | Issue type name (default `Task`) |

3. Run the server:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### API

- `GET /` — form UI
- `GET /api/health` — config presence check (no secrets)
- `POST /api/tickets` — JSON body `{ "title": "...", "description": "..." }`
