import json
import random
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent import drills
from app.agent.review import is_due, review_queue, schedule
from app.agent.session_memory import SessionStore
from app.agent.tools import dispatch_tool
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProvider, LLMResponse, ToolCall
from app.schemas import LearningLog, PracticeItem
from app.speech.base import Pronunciation, SpeechProvider

TODAY = date(2026, 10, 10)


def add(log, text, translation="", outcome="introduced", skill="speaking"):
    dispatch_tool(
        "record_practice",
        {"text": text, "kind": "sentence", "translation": translation, "outcome": outcome, "skill": skill},
        log,
    )


# --- Spaced repetition ---


def test_schedule_moves_up_boxes_and_resets_on_mistake():
    item = PracticeItem(text="huis")
    schedule(item, "introduced", TODAY)
    assert (item.review_box, item.next_review) == (0, "2026-10-11")
    schedule(item, "correct", TODAY)
    assert (item.review_box, item.next_review) == (1, "2026-10-11")
    schedule(item, "correct", TODAY)
    assert (item.review_box, item.next_review) == (2, "2026-10-13")
    schedule(item, "incorrect", TODAY)
    assert (item.review_box, item.next_review) == (0, "2026-10-10")


def test_review_queue_is_due_items_weakest_first():
    log = LearningLog(user_id="dave")
    log.practice_items = [
        PracticeItem(text="later", review_box=0, next_review="2026-10-20"),
        PracticeItem(text="strong", review_box=3, next_review="2026-10-01", attempts=4, correct=4),
        PracticeItem(text="weak", review_box=0, next_review="2026-10-09", attempts=2, correct=0),
        PracticeItem(text="unscheduled"),
    ]
    assert [i.text for i in review_queue(log, TODAY)] == ["weak", "strong"]
    assert not is_due(log.practice_items[3], TODAY)


class RecordingLLM(LLMProvider):
    def __init__(self, replies=None):
        self.calls = []
        self._replies = list(replies or [])

    def chat(self, messages, tools=None):
        self.calls.append((list(messages), tools))
        reply = self._replies.pop(0) if self._replies else LLMResponse(text="ok", raw_message={"role": "assistant", "content": "ok"})
        return reply


def test_session_start_lists_due_items_for_review(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("dave")
    log.profile.native_languages = ["English"]
    log.practice_items = [PracticeItem(text="het huis", translation="the house", next_review="2000-01-01")]
    store.save_log(log)
    llm = RecordingLLM()

    TutorAgent(llm=llm, store=store).start_session("dave")

    kickoff = llm.calls[0][0][-1]["content"]
    assert "review is due" in kickoff and "het huis (the house" in kickoff


# --- Second-opinion grading ---


def tool_reply(*calls):
    return LLMResponse(
        text=None,
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(calls)],
        raw_message={"role": "assistant", "content": None},
    )


def text_reply(text):
    return LLMResponse(text=text, raw_message={"role": "assistant", "content": text})


def test_grader_overrules_lenient_tutor_and_fixes_item(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    grader_json = json.dumps({"graded": [{
        "text": "Met mij gaat het goed, dank jij.", "correct": False,
        "correct_form": "Met mij gaat het goed, dank je.",
        "note": 'Use "dank je", not "dank jij".',
    }]})
    llm = RecordingLLM([
        tool_reply(("record_practice", {
            "text": "Met mij gaat het goed, dank jij.", "kind": "sentence",
            "translation": "I'm fine, thanks.", "outcome": "correct", "skill": "writing",
        })),
        text_reply("Heel goed!"),
        text_reply(grader_json),
    ])

    reply = TutorAgent(llm=llm, store=store).handle_message("dave", "Met mij gaat het goed, dank jij.")

    assert reply == 'Heel goed!\n\n✏️ Use "dank je", not "dank jij".'
    item = store.get_log("dave").practice_items[0]
    assert item.text == "Met mij gaat het goed, dank je."
    assert (item.attempts, item.correct, item.history[0].correct) == (1, 0, False)
    assert (item.review_box, item.next_review) == (0, date.today().isoformat())
    assert llm.calls[2][1] is None  # grader runs without tools


def test_grader_failure_keeps_tutor_grading(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    llm = RecordingLLM([
        tool_reply(("record_practice", {
            "text": "Ik woon in Utrecht.", "kind": "sentence", "translation": "I live in Utrecht.",
            "outcome": "correct", "skill": "writing",
        })),
        text_reply("Goed!"),
        text_reply("not json at all"),
    ])
    reply = TutorAgent(llm=llm, store=store).handle_message("dave", "Ik woon in Utrecht.")
    assert reply == "Goed!"
    assert store.get_log("dave").practice_items[0].correct == 1


# --- Pronunciation ---


def test_pronunciation_note_coaches_weak_words_and_tracks_focus(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    llm = RecordingLLM()
    pron = Pronunciation(overall=70, accuracy=65, fluency=90, words=[("ik", 95), ("Utrecht", 52)])

    TutorAgent(llm=llm, store=store).handle_message("dave", "Ik woon in Utrecht", channel="voice", pronunciation=pron)

    contents = [m["content"] for m in llm.calls[0][0]]
    assert any("overall 70" in c and "Weak words: Utrecht (52)" in c for c in contents)
    assert store.get_log("dave").pronunciation_focus == ["utrecht"]


# --- Drills ---


def drill_log():
    log = LearningLog(user_id="dave")
    add(log, "Hoe gaat het?", "How are you?")
    add(log, "Ik woon in ...", "I live in ...")  # pattern: not drillable
    add(log, "het huis", "the house")
    add(log, "de kat", "the cat")
    return log


def test_listening_grading_is_exact_but_reports_close_misses():
    log = drill_log()
    item = drills.find_item(log, "hoe gaat het")
    assert drills.grade(log, "listening", item, "hoe gaat het").correct
    close = drills.grade(log, "listening", item, "Hoe gaad het?")
    assert (close.correct, close.close) == (False, True)
    assert [(a.skill, a.correct) for a in item.history] == [("listening", True), ("listening", False)]


def test_reading_options_include_answer_and_distractors():
    log = drill_log()
    item = drills.find_item(log, "het huis")
    options = drills.reading_options(log, item, random.Random(1))
    assert "the house" in options and len(options) == 4 and len(set(options)) == 4
    assert drills.grade(log, "reading", item, "the house").correct
    assert item.history[-1].skill == "reading"


def test_pick_item_skips_patterns_and_prefers_due():
    log = drill_log()
    for _ in range(20):
        assert "..." not in drills.pick_item(log, TODAY, False, random.Random()).text
    log.practice_items[-1].next_review = "2000-01-01"
    assert drills.pick_item(log, TODAY, False, random.Random()).text == "de kat"


def test_drills_unavailable_without_items():
    with pytest.raises(drills.DrillUnavailable):
        drills.pick_item(LearningLog(user_id="dave"), TODAY, False, random.Random())


# --- API ---


class FakeSpeech(SpeechProvider):
    def __init__(self):
        self.rates = []

    def transcribe(self, audio_bytes, content_type):
        return ""

    def synthesize(self, text, rate="0%"):
        self.rates.append(rate)
        return f"mp3:{text}:{rate}".encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.api import routes
    from app.main import app

    store = SessionStore(data_dir=tmp_path)
    speech = FakeSpeech()
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(routes, "_speech", speech)
    return TestClient(app), store, speech


def test_conversation_endpoint_returns_current_turns(client):
    http, store, _ = client
    log = store.get_log("dave")
    add(log, "x")
    from app.schemas import ChatTurn
    log.current_conversation = [ChatTurn(role="assistant", content="Hallo!"), ChatTurn(role="user", content="Hoi")]
    store.save_log(log)
    assert http.get("/api/sessions/dave/conversation").json() == [
        {"role": "assistant", "content": "Hallo!"},
        {"role": "user", "content": "Hoi"},
    ]


def test_speak_endpoint_supports_slow_rate(client):
    http, _, speech = client
    res = http.post("/api/speak", json={"text": "Hallo", "slow": True})
    assert res.status_code == 200 and res.headers["content-type"] == "audio/mpeg"
    assert speech.rates == ["-30%"]


def test_listening_drill_round_trip(client):
    http, store, _ = client
    log = store.get_log("dave")
    add(log, "het huis", "the house")
    store.save_log(log)

    drill = http.post("/api/sessions/dave/drills/listening").json()
    assert drill["prompt_id"] == "het huis" and drill["audio_base64"] and drill["audio_slow_base64"]
    result = http.post("/api/sessions/dave/drills/listening/answer", json={"prompt_id": drill["prompt_id"], "answer": "Het huis."}).json()
    assert result["correct"] is True
    assert store.get_log("dave").practice_items[0].history[0].skill == "listening"


def test_reading_drill_needs_two_translated_items(client):
    http, store, _ = client
    log = store.get_log("dave")
    add(log, "het huis", "the house")
    store.save_log(log)
    res = http.post("/api/sessions/dave/drills/reading")
    assert res.status_code == 409


def test_progress_marks_due_items(client):
    http, store, _ = client
    log = store.get_log("dave")
    add(log, "het huis", "the house")
    log.practice_items[0].next_review = (date.today() - timedelta(days=1)).isoformat()
    store.save_log(log)
    assert http.get("/api/sessions/dave/progress").json()["items"][0]["due"] is True


def test_new_item_saved_in_wrong_form_is_corrected_even_when_tutor_agreed(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    # The tutor's reply already corrected it, so the audit gives no note.
    grader_json = json.dumps({"graded": [{
        "text": "Goed, dank jij.", "correct": False, "correct_form": "Goed, dank je.", "note": "",
    }]})
    llm = RecordingLLM([
        tool_reply(("record_practice", {
            "text": "Goed, dank jij.", "kind": "sentence", "translation": "Fine, thanks.",
            "outcome": "incorrect", "skill": "writing",
        })),
        text_reply('Almost! It is "dank je".'),
        text_reply(grader_json),
    ])
    reply = TutorAgent(llm=llm, store=store).handle_message("dave", "Goed, dank jij.")
    assert reply == 'Almost! It is "dank je".'  # tutor already corrected it: no extra note
    item = store.get_log("dave").practice_items[0]
    assert (item.text, item.correct, item.attempts) == ("Goed, dank je.", 0, 1)


def test_wrong_form_attempt_is_merged_into_existing_correct_item(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("dave")
    add(log, "Ik woon in Utrecht.", "I live in Utrecht.", outcome="correct", skill="writing")
    store.save_log(log)
    grader_json = json.dumps({"graded": [{
        "text": "Ik woon in de Utrecht.", "correct": False, "correct_form": "Ik woon in Utrecht.", "note": "",
    }]})
    llm = RecordingLLM([
        tool_reply(("record_practice", {
            "text": "Ik woon in de Utrecht.", "kind": "sentence", "translation": "I live in Utrecht.",
            "outcome": "incorrect", "skill": "writing",
        })),
        text_reply("No 'de' before city names."),
        text_reply(grader_json),
    ])
    TutorAgent(llm=llm, store=store).handle_message("dave", "Ik woon in de Utrecht.")

    items = store.get_log("dave").practice_items
    assert [(i.text, i.correct, i.attempts) for i in items] == [("Ik woon in Utrecht.", 1, 2)]
    assert items[0].review_box == 0  # the mistake resets its review schedule


def test_audit_records_items_the_tutor_forgot(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    audit_json = json.dumps({"graded": [], "missed": [
        {"text": "En met jou?", "kind": "sentence", "translation": "And you?", "outcome": "introduced", "note": ""},
        {"text": "Ik heet Goro.", "kind": "sentence", "translation": "My name is Goro.", "outcome": "incorrect",
         "note": 'Say "Ik heet", not "Ik heb".'},
    ]})
    llm = RecordingLLM([text_reply('Goed! Now try "En met jou?"'), text_reply(audit_json)])

    reply = TutorAgent(llm=llm, store=store).handle_message("dave", "Ik heb Goro.", channel="voice")

    assert reply.endswith('✏️ Say "Ik heet", not "Ik heb".')
    items = {i.text: i for i in store.get_log("dave").practice_items}
    assert items["En met jou?"].attempts == 0 and items["En met jou?"].next_review
    assert [(a.skill, a.correct) for a in items["Ik heet Goro."].history] == [("speaking", False)]


def test_audit_runs_at_session_start_for_taught_items(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    audit_json = json.dumps({"graded": [], "missed": [
        {"text": "Goedemorgen", "kind": "word", "translation": "Good morning", "outcome": "introduced", "note": ""},
    ]})
    llm = RecordingLLM([text_reply("Today: 'Goedemorgen' means good morning."), text_reply(audit_json)])
    TutorAgent(llm=llm, store=store).start_session("dave")
    assert [i.text for i in store.get_log("dave").practice_items] == ["Goedemorgen"]


def test_no_duplicate_note_when_tutor_already_corrected(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    audit_json = json.dumps({
        "graded": [{"text": "twee broodje", "correct": False, "correct_form": "twee broodjes",
                    "note": "The plural is broodjes."}],
        "missed": [{"text": "Ik wil een koffie.", "kind": "sentence", "translation": "I want a coffee.",
                    "outcome": "incorrect", "note": "Say 'een koffie'."}],
    })
    llm = RecordingLLM([
        tool_reply(("record_practice", {"text": "twee broodje", "kind": "sentence", "translation": "two rolls",
                                        "outcome": "incorrect", "skill": "writing"})),
        text_reply('Almost: "twee broodjes". And it is "Ik wil een koffie."'),
        text_reply(audit_json),
    ])
    reply = TutorAgent(llm=llm, store=store).handle_message("dave", "Ik wil koffie en twee broodje.")
    assert "✏️" not in reply
