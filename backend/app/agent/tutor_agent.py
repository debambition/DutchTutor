"""Core orchestration: builds the prompt from the spec + learner state, calls
the LLM (with tool calling for structured memory updates), and persists the
resulting learning log.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.agent.progress import skill_progress
from app.agent.audit import audit_turn
from app.agent.review import review_queue, schedule
from app.agent.session_memory import SessionStore
from app.agent.spec_loader import load_system_prompt
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool, practice_key
from app.llm.base import LLMProvider, LLMProviderError
from app.schemas import ChatTurn, LearningLog
from app.speech.base import Pronunciation

MAX_TOOL_ITERATIONS = 5
# Words scoring below this in pronunciation assessment get coached and are
# added to the learner's pronunciation focus list.
WEAK_PRONUNCIATION_SCORE = 75
MAX_PRONUNCIATION_FOCUS = 20
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
            due = review_queue(log, date.today())
            if due:
                listed = "; ".join(
                    f"{i.text} ({i.translation or 'no translation'}, "
                    f"{'never practised' if i.score is None else f'{i.score}% so far'})"
                    for i in due
                )
                kickoff += (
                    " Spaced-repetition review is due for these items, weakest "
                    f"first: {listed}. In the warm-up, quiz the learner on them "
                    "one at a time (recall or use in a sentence) and record each "
                    "attempt with record_practice before moving on to new material."
                )
        messages = self._build_messages(log, None)
        messages.append({"role": "system", "content": kickoff})
        before = self._snapshot(log)
        reply = self._run_completion_loop(messages, log)
        reply += self._audit(log, before, None, reply, None)
        log.current_conversation.append(ChatTurn(role="assistant", content=reply))
        self._store.save_log(log)
        return reply

    def handle_message(
        self,
        user_id: str,
        user_text: str,
        channel: str = "text",
        pronunciation: Pronunciation | None = None,
    ) -> str:
        """`channel` is "voice" when the message was transcribed speech, so
        attempts can be attributed to speaking rather than writing.
        `pronunciation` is the speech service's assessment of that audio."""
        log = self._store.get_log(user_id)
        messages = self._build_messages(log, user_text)
        how = "spoke this aloud (transcribed speech)" if channel == "voice" else "typed this"
        messages.insert(-1, {"role": "system", "content": f"The learner {how}."})
        if pronunciation is not None:
            messages.insert(-1, {"role": "system", "content": self._pronunciation_note(log, pronunciation)})
        before = self._snapshot(log)
        reply = self._run_completion_loop(messages, log, channel=channel)
        reply += self._audit(log, before, user_text, reply, channel)

        log.current_conversation.append(ChatTurn(role="user", content=user_text))
        log.current_conversation.append(ChatTurn(role="assistant", content=reply))
        self._store.save_log(log)
        return reply

    @staticmethod
    def _pronunciation_note(log: LearningLog, pronunciation: Pronunciation) -> str:
        weak = [(w, score) for w, score in pronunciation.words if score < WEAK_PRONUNCIATION_SCORE]
        for word, _ in weak:
            word = word.lower()
            if word in log.pronunciation_focus:
                log.pronunciation_focus.remove(word)
            log.pronunciation_focus.append(word)
        del log.pronunciation_focus[:-MAX_PRONUNCIATION_FOCUS]
        note = (
            "Pronunciation assessment of the learner's audio (0-100): "
            f"overall {pronunciation.overall:.0f}, accuracy {pronunciation.accuracy:.0f}, "
            f"fluency {pronunciation.fluency:.0f}."
        )
        if weak:
            listed = ", ".join(f"{w} ({score:.0f})" for w, score in weak)
            note += (
                f" Weak words: {listed}. Briefly coach how to pronounce them "
                "(one tip each) and invite the learner to say them again."
            )
        else:
            note += " No weak words — a quick word of praise for the pronunciation is enough."
        return note

    @staticmethod
    def _snapshot(log: LearningLog) -> dict[str, tuple[int, int, str]]:
        """Per-item state before a turn, so the audit can see what changed."""
        return {
            practice_key(i.text): (len(i.history), i.review_box, i.next_review)
            for i in log.practice_items
        }

    def _audit(
        self,
        log: LearningLog,
        before: dict[str, tuple[int, int, str]],
        learner_text: str | None,
        reply: str,
        channel: str | None,
    ) -> str:
        """Audit this turn's tracking (see app/agent/audit.py) and apply it:
        fix grading disagreements and record anything the tutor missed.
        Returns a correction note to append to the reply (else "")."""
        graded = []  # (item, new attempts, snapshot or None)
        introduced = []
        for item in log.practice_items:
            snapshot = before.get(practice_key(item.text))
            new = item.history[snapshot[0] if snapshot else 0 :]
            if new:
                graded.append((item, new, snapshot))
            elif snapshot is None:
                introduced.append(item.text)
        try:
            audit = audit_turn(
                self._llm,
                learner_text,
                reply,
                introduced,
                [(item.text, new[-1].correct) for item, new, _ in graded],
                log.profile.resolved_feedback_language(),
                channel,
            )
        except LLMProviderError:
            return ""  # keep the tutor's records as they are

        notes = []
        today = date.today()
        by_key = {practice_key(v.text): v for v in audit.graded}
        for item, new, snapshot in graded:
            verdict = by_key.get(practice_key(item.text))
            if verdict is None:
                continue
            tutor_accepted = new[-1].correct
            if verdict.correct != tutor_accepted:
                item.correct += sum(verdict.correct - a.correct for a in new)
                for attempt in new:
                    attempt.correct = verdict.correct
                # Replay this turn's scheduling with the corrected outcomes.
                item.review_box, item.next_review = snapshot[1:] if snapshot else (0, "")
                for attempt in new:
                    schedule(item, "correct" if attempt.correct else "incorrect", today)
            # Only add a note when the tutor let the mistake pass; if it marked
            # the attempt incorrect, its reply already dealt with it.
            if tutor_accepted and not verdict.correct and verdict.note:
                notes.append(verdict.note)
            if not verdict.correct and not snapshot:
                self._track_correct_form(log, item, new, verdict.correct_form, today)

        recorded = {practice_key(item.text) for item, _, _ in graded} | {
            practice_key(text) for text in introduced
        }
        for missed in audit.missed:
            if practice_key(missed.text) in recorded:
                continue
            recorded.add(practice_key(missed.text))
            dispatch_tool(
                "record_practice",
                {
                    "text": missed.text,
                    "kind": missed.kind,
                    "translation": missed.translation,
                    "outcome": missed.outcome,
                    # Attempts in chat are production; the channel decides
                    # speaking vs writing.
                    "skill": "writing",
                },
                log,
                channel=channel,
            )
            if (
                missed.outcome == "incorrect"
                and missed.note
                and practice_key(missed.text) not in practice_key(reply)
            ):
                notes.append(missed.note)  # the reply never showed the correct form
        return f"\n\n✏️ {' '.join(notes)}" if notes else ""

    @staticmethod
    def _track_correct_form(log, item, new, correct_form: str, today: date) -> None:
        """A brand-new item recorded in the learner's wrong form should track
        the correct form: rename it, or fold its attempts into the existing
        item for that form."""
        form_key = practice_key(correct_form)
        if not form_key or form_key == practice_key(item.text):
            return
        existing = next((i for i in log.practice_items if practice_key(i.text) == form_key), None)
        if existing is None:
            item.text = correct_form
            return
        existing.history.extend(new)
        existing.attempts += len(new)
        existing.correct += sum(a.correct for a in new)
        existing.last_seen = item.last_seen
        existing.translation = existing.translation or item.translation
        for attempt in new:
            schedule(existing, "correct" if attempt.correct else "incorrect", today)
        log.practice_items.remove(item)

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
