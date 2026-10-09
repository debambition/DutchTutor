# Backend — Dutch Tutor Agent

FastAPI service implementing the agent defined in
[`../dutch-tutor-agent-spec.md`](../dutch-tutor-agent-spec.md), with pluggable
LLM and speech providers.

## Setup

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env: set LLM_PROVIDER / SPEECH_PROVIDER and the matching credentials
```

Leaving `LLM_PROVIDER=mock` and `SPEECH_PROVIDER=mock` (the defaults) lets you
run the whole app with zero API keys, to verify the plumbing before wiring
real credentials.

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/ — the FastAPI server also serves the simple chat
UI from `../frontend`.

## Test

```powershell
pytest
```

## Architecture

- `app/agent/spec_loader.py` — loads `dutch-tutor-agent-spec.md` as the system prompt (single source of truth).
- `app/agent/session_memory.py` — per-user learning log persistence (local JSON under `data/users/`, gitignored).
- `app/agent/tools.py` — function-calling schemas + dispatcher the LLM uses to update levels/vocabulary/grammar/errors/session summaries.
- `app/agent/tutor_agent.py` — orchestrates one turn: builds messages, runs the LLM + tool-call loop, persists state.
- `app/llm/` — provider-agnostic LLM interface (`mock`, `openai`, `azure_openai`).
- `app/speech/` — provider interface for speech-to-text/text-to-speech (`mock`, `azure`).
- `app/api/routes.py` — HTTP endpoints: start/message/voice/end session, profile get/put.

## Switching providers

Set in `.env`:

- `LLM_PROVIDER=azure_openai` with `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`
- `LLM_PROVIDER=openai` with `OPENAI_API_KEY`
- `SPEECH_PROVIDER=azure` with `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`

No code changes needed — the factories in `app/llm/factory.py` and
`app/speech/factory.py` pick the implementation at startup.
