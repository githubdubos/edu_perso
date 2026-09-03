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

- Intent sketch + optional **Wiki page** (ma-banking Confluence title or URL) + optional **Client ticket** reference + title, description, **Parent issue**, and **Team** inputs (parent pre-filled with `ATL-25692`; team with `BC.RCOFit+LR`)
- **Suggest with AI** — loads wiki + client ticket content when provided, fetches recent child tickets under the form parent (default `ATL-25692`), asks **Cursor** (default) to draft title/description, and fills the form (does **not** create the issue). Optional fallbacks: Gemini / OpenAI / Azure via `SUGGEST_PROVIDER`
- **Create ticket** — validate → create via REST API v3 under the form parent key → show link → clear title/description on success
- New issues are created in `JIRA_PROJECT_KEY` (default `ATL`) with `parent` from the form (fallback: `JIRA_PARENT_KEY`, default `ATL-25692`) — verified for ATL `Task` under that epic (legacy backlog children are often RAY Stories; samples still come from all children of the epic)
- **Team** maps to Jira Cloud `customfield_10001` as the team **id** string (create-meta accepts it for ATL Task). The UI shows the friendly name; empty Team omits the field

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
| `JIRA_PROJECT_KEY` | yes | Target project for **new** issues (default `ATL` under epic ATL-25692; verified) |
| `JIRA_ISSUE_TYPE` | no | Issue type name (default `Task`; Story also works in ATL) |
| `JIRA_PARENT_KEY` | no | Parent epic key for AI samples + create fallback when the form field is empty (default `ATL-25692`) |
| `JIRA_SAMPLE_LIMIT` | no | Number of recent child tickets sent as style samples (default `8`, max `20`) |
| `JIRA_TEAM_NAME` | no | Default Team label in the UI / name→id map (default `BC.RCOFit+LR`) |
| `JIRA_TEAM_ID` | no | Atlassian Team id sent as `customfield_10001` (default id for `BC.RCOFit+LR` from ATL-25692) |
| `SUGGEST_PROVIDER` | no | `cursor` (default), or `gemini` / `openai` / `azure` |
| `CURSOR_API_KEY` | for Cursor Suggest | User/service API key from [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) |
| `CURSOR_MODEL` | no | Cursor SDK model id (default `composer-2.5`) |
| `CURSOR_RUNTIME` | no | `local` (default) or `cloud` (no-repo cloud agent) |
| `CURSOR_SUGGEST_TIMEOUT_SECONDS` | no | Bridge wait timeout in seconds (default `120`) |
| `CURSOR_SUGGEST_WEBHOOK_URL` | bridge only | Automations webhook URL when `CURSOR_API_KEY` is unset |
| `OPENAI_API_KEY` | for OpenAI Suggest | OpenAI API key |
| `OPENAI_MODEL` | no | OpenAI model (default `gpt-4o-mini`) |
| `AZURE_OPENAI_API_KEY` | for Azure Suggest | Azure OpenAI key |
| `AZURE_OPENAI_ENDPOINT` | for Azure Suggest | e.g. `https://your-resource.openai.azure.com` |
| `AZURE_OPENAI_DEPLOYMENT` | for Azure Suggest | Deployment name |
| `AZURE_OPENAI_API_VERSION` | no | Azure API version (default `2024-08-01-preview`) |
| `GEMINI_API_KEY` | for Gemini Suggest | Gemini Developer API key ([AI Studio](https://aistudio.google.com/app/api-keys)); `GOOGLE_API_KEY` also accepted |
| `GEMINI_MODEL` | no | Gemini model (default `gemini-2.0-flash`) |
| `LLM_PROVIDER` | no | Still used when resolving classic LLM keys; Suggest prefers `SUGGEST_PROVIDER` |

3. Run the server:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### How Suggest via Cursor works

Default `SUGGEST_PROVIDER=cursor`:

1. You enter an intent sketch (required), optionally a wiki page (title or URL) and a client ticket key/URL, then click **Suggest with AI**.
2. The UI shows **Asking Cursor…** while `POST /api/suggest` runs.
3. The server fetches the Confluence page body and/or client Jira issue when those fields are set, and loads recent issues with JQL `parent = <parent>` (form parent, else `JIRA_PARENT_KEY`).
4. Those sources + your intent are sent to a **Cursor Cloud Agent** via `https://api.cursor.com` (no-repo run), using `CURSOR_API_KEY`. (The Python `cursor-sdk` local Bridge is avoided on Windows because of a known WinError 10038.)
5. After the cloud run finishes (~30–90s), the agent returns JSON `{ "title", "description" }`. The form is filled. You still click **Create ticket** yourself.

One-time Cursor setup:

1. Open [Cursor Dashboard → Integrations](https://cursor.com/dashboard/integrations) and create a user API key.
2. Put it in `.env` as `CURSOR_API_KEY=...` (never commit `.env`).
3. `pip install -r requirements.txt` and restart uvicorn.
4. Optional: set `CURSOR_MODEL` / `CURSOR_RUNTIME=local|cloud`.

#### Optional: Automations file/webhook bridge

If you cannot use `CURSOR_API_KEY`, set `CURSOR_SUGGEST_WEBHOOK_URL` to a Cursor Automation webhook. On Suggest the app:

1. Writes `.data/suggest/<id>.request.json` (gitignored)
2. POSTs the payload to the webhook
3. Waits until `.data/suggest/<id>.response.json` appears (or until timeout)

Create the Automation once in Cursor:

1. Open **Automations** (or ask an agent to open it with a webhook draft).
2. Trigger: **On an incoming HTTP webhook**.
3. Instructions for the agent (summary): read the webhook JSON (`intent`, `samples`, `prompt`); draft a Jira title/description matching sample style; either write `{ "title", "description" }` to the path in `response_path` (local/dev) **or** `POST` the same JSON to `http://127.0.0.1:8000/api/suggest/<id>/complete` when the app is reachable from the Automation runner.
4. Save, copy the webhook URL into `CURSOR_SUGGEST_WEBHOOK_URL`, restart the app.

Note: cloud Automations cannot write to your local disk and usually cannot reach `127.0.0.1`. Prefer `CURSOR_API_KEY` + the SDK for a reliable local Suggest button. The bridge is for experiments / custom wiring.

#### Classic LLM fallbacks

```powershell
# In .env — only if you intentionally want Gemini/OpenAI instead of Cursor
SUGGEST_PROVIDER=gemini
GEMINI_API_KEY=your-ai-studio-key
GEMINI_MODEL=gemini-2.0-flash
```

Internal guide (billing, GCP project, Vertex vs Developer API): [How to programmatically call AI (LLM / Gemini)](https://ma-banking.atlassian.net/wiki/spaces/ERFS/pages/442106176/How+to+programmatically+call+AI+LLM+Gemini).

### API

- `GET /` — form UI
- `GET /api/health` — Jira/Suggest config presence check (no secrets); includes `suggest_provider`
- `POST /api/suggest` — JSON body `{ "intent": "...", "parent_key": "...", "team": "..." }` → `{ title, description, samples_used, parent_key, provider }`
- `POST /api/suggest/{id}/complete` — bridge completion `{ "title", "description" }` or `{ "error" }`
- `POST /api/tickets` — JSON body `{ "title": "...", "description": "...", "parent_key": "ATL-25692", "team": "BC.RCOFit+LR" }` (`parent_key` optional; empty falls back to `JIRA_PARENT_KEY`; `team` optional; empty omits `customfield_10001`)
