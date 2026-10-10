"""Core orchestration: builds the prompt from the spec + learner state, calls
the LLM (with tool calling for structured memory updates), and persists the
resulting learning log.
"""
from __future__ import annotations

from typing import Any

from app.agent.progress import skill_progress
from app.agent.session_memory import SessionStore
from app.agent.spec_loader import load_system_prompt
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool
from app.llm.base import LLMProvider
from app.schemas import ChatTurn, LearningLog

MAX_TOOL_ITERATIONS = 5
# Keep the context window bounded for a scaffold; a production system would
# summarize older turns instead of truncating them.
MAX_HISTORY_TURNS = 20

# Sent as the last system message each turn: models follow a checklist placed
# right before they answer far more reliably than one buried in the prompt.
PRACTICE_TRACKING_REMINDER = (
    "Progress tracking — before writing your reply, call record_practice:\n"
    "1. For each Dutch word or sentence the learner attempted in their last "
    "message: outcome 'correct' or 'incorrect' (one call per item), with the "
    "skill the attempt exercised.\n"
    "2. For each new Dutch word or sentence you are about to teach or ask them "
    "to practise in this reply: outcome 'introduced', with a translation in "
    "the learner's feedback language.\n"
    "Use the canonical Dutch form (e.g. 'Ik woon in ...') so repeats match. "
    "Skip this only when no Dutch is being taught or attempted."
)


class TutorAgent:
    def __init__(self, llm: LLMProvider, store: SessionStore) -> None:
        self._llm = llm
        self._store = store

    def _state_summary(self, log: LearningLog) -> str:
        last_focus = log.sessions[-1].next_focus if log.sessions else "(no prior sessions)"
        return (
            "Current learner state (from persisted learning log):\n"
            f"- Profile: {log.profile.model_dump()}\n"
            f"- Levels: {log.levels.model_dump()}\n"
            f"- Known vocabulary: {log.vocabulary.known}\n"
            f"- Struggling vocabulary: {log.vocabulary.struggling}\n"
            f"- Mastered grammar: {log.grammar.mastered}\n"
            f"- Weak grammar points: {log.grammar.weak_points}\n"
            f"- Recurring errors: {[e.pattern for e in log.recurring_errors]}\n"
            f"- Suggested focus from last session: {last_focus}\n"
            f"- Number of prior sessions: {len(log.sessions)}\n"
            f"{self._readiness_note(log)}"
            "- Feedback language (for the end-of-session summary and "
            f"record_practice translations): {log.profile.resolved_feedback_language()}\n"
            "Use the provided tools to keep this state up to date as the "
            "conversation progresses."
        )

    @staticmethod
    def _readiness_note(log: LearningLog) -> str:
        ready = [
            f"{p.skill} ({p.level} -> {p.next_level})"
            for p in skill_progress(log)
            if p.next_level and p.percent >= 100
        ]
        if not ready:
            return ""
        return (
            "- Score-based progress suggests the learner may be ready to move up in: "
            f"{', '.join(ready)}. Consider a short level check for these skills and "
            "call update_skill_level if they pass.\n"
        )

    def _build_messages(self, log: LearningLog, new_user_text: str | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": load_system_prompt()},
            {"role": "system", "content": self._state_summary(log)},
        ]
        for turn in log.current_conversation[-MAX_HISTORY_TURNS:]:
            messages.append({"role": turn.role, "content": turn.content})
        if new_user_text is not None:
            messages.append({"role": "user", "content": new_user_text})
        messages.append({"role": "system", "content": PRACTICE_TRACKING_REMINDER})
        return messages

    def _run_completion_loop(
        self, messages: list[dict[str, Any]], log: LearningLog, channel: str | None = None
    ) -> str:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._llm.chat(messages, tools=TOOL_SCHEMAS)
            if not response.tool_calls:
                return response.text or ""

            messages.append(response.raw_message)
            for call in response.tool_calls:
                result = dispatch_tool(call.name, call.arguments, log, channel=channel)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )
        # Safety net if the model loops on tool calls without ever answering.
        return "(The tutor is still thinking — please try again.)"

    def start_session(self, user_id: str) -> str:
        """Kick off a session: full intake for a new learner, or a short
        warm-up/review for a returning one (per spec section 7)."""
        log = self._store.get_log(user_id)
        log.current_conversation = []
        log.active_session = len(log.sessions) + 1
        if not log.sessions and not log.profile.native_languages:
            kickoff = (
                "This is the learner's first-ever session. Greet them and run "
                "the full profile intake in English (not Dutch) — their native "
                "language and Dutch level are still unknown."
            )
        else:
            kickoff = (
                "This is the start of a new session. Give a short "
                "warm-up/review referencing prior sessions, then continue "
                "per the session structure in the spec."
            )
        messages = self._build_messages(log, None)
        messages.append({"role": "system", "content": kickoff})
        reply = self._run_completion_loop(messages, log)
        log.current_conversation.append(ChatTurn(role="assistant", content=reply))
        self._store.save_log(log)
        return reply

    def handle_message(self, user_id: str, user_text: str, channel: str = "text") -> str:
        """`channel` is "voice" when the message was transcribed speech, so
        attempts can be attributed to speaking rather than writing."""
        log = self._store.get_log(user_id)
        messages = self._build_messages(log, user_text)
        how = "spoke this aloud (transcribed speech)" if channel == "voice" else "typed this"
        messages.insert(-1, {"role": "system", "content": f"The learner {how}."})
        reply = self._run_completion_loop(messages, log, channel=channel)

        log.current_conversation.append(ChatTurn(role="user", content=user_text))
        log.current_conversation.append(ChatTurn(role="assistant", content=reply))
        self._store.save_log(log)
        return reply

    def end_session(self, user_id: str) -> str:
        """Produce the end-of-session feedback report (spec section 10) and
        persist a session summary via the record_session_summary tool."""
        log = self._store.get_log(user_id)
        language = log.profile.resolved_feedback_language()
        kickoff = (
            "The learner wants to end the session now. Produce the "
            "end-of-session feedback required by the spec (topics/vocabulary "
            "covered, grammar practiced, mistakes and corrections, current "
            "per-skill levels, suggested focus for next time), and call "
            "record_session_summary with that information. "
            f"Write the entire feedback in {language}, the learner's chosen "
            "feedback language — not in Dutch. Only the Dutch words, phrases "
            "and corrections being reviewed stay in Dutch."
        )
        messages = self._build_messages(log, None)
        messages.append({"role": "system", "content": kickoff})
        reply = self._run_completion_loop(messages, log)

        log.current_conversation.append(ChatTurn(role="assistant", content=reply))
        self._store.save_log(log)
        return reply
