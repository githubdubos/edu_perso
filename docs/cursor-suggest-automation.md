# Cursor Automation — Jira Suggest bridge (optional)

Use this only when `CURSOR_API_KEY` is unavailable. Prefer the Cursor SDK path documented in the root README.

## Goal

When the FastAPI app receives **Suggest with AI** without an API key, it POSTs a JSON payload to `CURSOR_SUGGEST_WEBHOOK_URL` and waits for a response file or `POST /api/suggest/{id}/complete`.

## Suggested Automation draft

| Draft field | Value |
|-------------|-------|
| Name / description | Jira Suggest bridge — draft title/description for edu_perso Suggest button |
| Trigger | Incoming HTTP webhook |
| Tools | (minimal; no repo edits required if samples are in the payload) |
| Instructions | On webhook: read JSON fields `id`, `intent`, `samples`, `prompt`. Draft a Jira ticket title and description matching sample style. Reply with JSON only: `{"title":"...","description":"..."}`. If you can reach the local app, POST that JSON to `http://127.0.0.1:8000/api/suggest/<id>/complete`. Otherwise write the same object to the path in `response_path` (local runners only). Never create the Jira issue. |
| Resolved settings | Webhook URL copied into `.env` as `CURSOR_SUGGEST_WEBHOOK_URL` |
| To finish in editor | Save automation, copy webhook URL + auth into `.env`, restart uvicorn |

## Enable once

1. Open Cursor **Automations** UI and create a new automation with a **webhook** trigger.
2. Paste the instructions above.
3. Save and copy the webhook URL into `.env` → `CURSOR_SUGGEST_WEBHOOK_URL=...`
4. Keep `SUGGEST_PROVIDER=cursor` and leave `CURSOR_API_KEY` empty for bridge-only mode (or set the API key to use the SDK instead and ignore this file).
