# DutchTutor

An AI-based tool to learn Dutch, built around an adaptive tutoring agent that
personalizes pace, correction style, and topics to each learner's profile and
tracks progress across sessions.

## Getting Started

The implementation lives in [`backend/`](./backend) (FastAPI agent service,
pluggable LLM/speech providers) and [`frontend/`](./frontend) (a minimal
chat + voice web UI served by the backend). See
[`backend/README.md`](./backend/README.md) for setup/run/test instructions.

## Project Artifacts

- [`dutch-tutor-agent-spec.md`](./dutch-tutor-agent-spec.md) — the structured
  system prompt / agent specification (source of truth for agent behavior).
- [`lang-skill.md`](./lang-skill.md) — original raw project prompt (history).
- [`lang-skill v1.md`](./lang-skill%20v1.md) — refined prompt draft (history).
