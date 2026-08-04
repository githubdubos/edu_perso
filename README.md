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

Small FastAPI web app to create Jira issues from a simple form, with optional AI-assisted drafting inspired by existing tickets under a parent epic. Patterns borrowed lightly from other Regnology sandboxes (`configops-mcp-server` for Jira REST, Teams AI agent for env-driven LLM config), kept minimal here.

### Features

- Intent sketch + title and description inputs
- **Suggest with AI** — fetches recent child tickets under `JIRA_PARENT_KEY` (default `ATL-25692`), asks an LLM to draft title/description in the same style, and fills the form (does **not** create the issue)
- **Create ticket** — validate → create via REST API v3 → show link → clear fields on success
- New issues are created with `parent = JIRA_PARENT_KEY` when that env var is set (on this Jira Cloud site, children of epic ATL-25692 use the **parent** field, not a separate Epic Link)

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
| `JIRA_PROJECT_KEY` | yes | Target project for **new** issues (for ATL-25692 backlog children, typically `RAY`) |
| `JIRA_ISSUE_TYPE` | no | Issue type name (default `Story`) |
| `JIRA_PARENT_KEY` | no | Parent epic key for samples + create linkage (default `ATL-25692`) |
| `JIRA_SAMPLE_LIMIT` | no | Number of recent child tickets sent to the LLM (default `8`, max `20`) |
| `OPENAI_API_KEY` | for AI (OpenAI) | OpenAI API key |
| `OPENAI_MODEL` | no | OpenAI model (default `gpt-4o-mini`) |
| `AZURE_OPENAI_API_KEY` | for AI (Azure) | Azure OpenAI key |
| `AZURE_OPENAI_ENDPOINT` | for AI (Azure) | e.g. `https://your-resource.openai.azure.com` |
| `AZURE_OPENAI_DEPLOYMENT` | for AI (Azure) | Deployment name |
| `AZURE_OPENAI_API_VERSION` | no | Azure API version (default `2024-08-01-preview`) |
| `GEMINI_API_KEY` | for AI (Gemini) | Gemini Developer API key ([AI Studio](https://aistudio.google.com/app/api-keys)); `GOOGLE_API_KEY` also accepted |
| `GEMINI_MODEL` | no | Gemini model (default `gemini-2.0-flash`) |
| `LLM_PROVIDER` | no | Force `openai`, `azure`, or `gemini`; otherwise Azure → OpenAI → Gemini by first key found |

3. Run the server:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### How AI suggestion works

1. You enter an intent sketch (or reuse title/description as the sketch).
2. `POST /api/suggest` loads recent issues with JQL `parent = <JIRA_PARENT_KEY>` via Jira REST (same credentials as create).
3. Those samples (summary, description, type, labels, components, priority) plus your intent are sent to OpenAI, Azure OpenAI, or Gemini.
4. The response fills **Title** and **Description** in the form. You review/edit, then click **Create ticket**.

If no LLM key is configured, the suggest endpoint returns a clear `503` listing the missing env vars. Create still works without an LLM key.

#### Gemini setup (local / AI Studio)

Simplest local path: Gemini Developer API with an API key from [Google AI Studio](https://aistudio.google.com/app/api-keys) (`google-genai`).

```powershell
# In .env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-ai-studio-key
GEMINI_MODEL=gemini-2.0-flash
```

Then reinstall deps if needed and **restart uvicorn** so env changes load:

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Internal guide (billing, GCP project, Vertex vs Developer API): [How to programmatically call AI (LLM / Gemini)](https://ma-banking.atlassian.net/wiki/spaces/ERFS/pages/442106176/How+to+programmatically+call+AI+LLM+Gemini).

### API

- `GET /` — form UI
- `GET /api/health` — Jira/LLM config presence check (no secrets)
- `POST /api/suggest` — JSON body `{ "intent": "..." }` → `{ title, description, samples_used, parent_key }`
- `POST /api/tickets` — JSON body `{ "title": "...", "description": "..." }` (creates under parent when configured)
