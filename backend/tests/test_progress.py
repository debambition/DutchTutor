from app.agent.session_memory import SessionStore
from app.agent.tools import dispatch_tool
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProvider, LLMResponse
from app.schemas import LearningLog, Profile, SessionRecord


class RecordingLLMProvider(LLMProvider):
    """Captures the messages it is sent and replies with fixed text."""

    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, tools=None) -> LLMResponse:
        self.messages = list(messages)
        return LLMResponse(text="Summary", tool_calls=[], raw_message={"role": "assistant", "content": "Summary"})


def test_record_practice_tracks_attempts_and_score():
    log = LearningLog(user_id="dave")
    dispatch_tool("record_practice", {"text": "Ik heet", "kind": "sentence", "translation": "My name is", "outcome": "introduced"}, log)
    dispatch_tool("record_practice", {"text": "ik heet.", "kind": "sentence", "outcome": "incorrect"}, log)
    dispatch_tool("record_practice", {"text": "Ik heet", "kind": "sentence", "outcome": "correct"}, log)
    dispatch_tool("record_practice", {"text": "Ik heet", "kind": "sentence", "outcome": "correct"}, log)

    assert len(log.practice_items) == 1
    item = log.practice_items[0]
    assert (item.text, item.translation, item.attempts, item.correct) == ("Ik heet", "My name is", 3, 2)
    assert item.score == 67


def test_record_practice_unpractised_item_has_no_score():
    log = LearningLog(user_id="dave")
    dispatch_tool("record_practice", {"text": "huis", "kind": "word", "outcome": "introduced"}, log)
    assert log.practice_items[0].score is None


def test_record_practice_keeps_most_recent_activity_last():
    log = LearningLog(user_id="dave")
    for word in ("huis", "kat", "hond"):
        dispatch_tool("record_practice", {"text": word, "kind": "word", "outcome": "introduced"}, log)
    dispatch_tool("record_practice", {"text": "huis", "kind": "word", "outcome": "correct"}, log)
    assert [i.text for i in log.practice_items] == ["kat", "hond", "huis"]


def test_record_practice_notes_session_number():
    log = LearningLog(user_id="dave", sessions=[SessionRecord(date="2026-10-01")])
    dispatch_tool("record_practice", {"text": "huis", "kind": "word", "outcome": "introduced"}, log)
    assert log.practice_items[0].first_session == 2


def test_feedback_language_falls_back_to_native_then_english():
    assert Profile(feedback_language="Hindi", native_languages=["Spanish"]).resolved_feedback_language() == "Hindi"
    assert Profile(native_languages=["Spanish"]).resolved_feedback_language() == "Spanish"
    assert Profile().resolved_feedback_language() == "English"


def test_end_session_asks_for_feedback_in_chosen_language(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("dave")
    log.profile.feedback_language = "Hindi"
    store.save_log(log)
    llm = RecordingLLMProvider()

    TutorAgent(llm=llm, store=store).end_session("dave")

    kickoff = llm.messages[-1]["content"]
    assert "Write the entire feedback in Hindi" in kickoff
    assert "not in Dutch" in kickoff


def test_this_session_items_stay_visible_after_session_ends(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app

    store = SessionStore(data_dir=tmp_path)
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(routes, "_agent", TutorAgent(llm=RecordingLLMProvider(), store=store))
    client = TestClient(app)

    client.post("/api/sessions/dave/start")
    log = store.get_log("dave")
    dispatch_tool("record_practice", {"text": "huis", "kind": "word", "translation": "house", "outcome": "correct"}, log)
    dispatch_tool("record_session_summary", {"topics_covered": ["home"], "next_focus": "food"}, log)
    store.save_log(log)

    items = client.get("/api/sessions/dave/progress").json()["items"]
    assert [(i["text"], i["score"], i["this_session"]) for i in items] == [("huis", 100, True)]

    client.post("/api/sessions/dave/start")
    items = client.get("/api/sessions/dave/progress").json()["items"]
    assert items[0]["this_session"] is False


def test_progress_lists_vocabulary_from_past_session_summaries(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app

    store = SessionStore(data_dir=tmp_path)
    monkeypatch.setattr(routes, "_store", store)
    log = store.get_log("dave")
    log.sessions = [SessionRecord(date="2026-10-01", vocabulary_introduced=["werk", "kantoor", "Huis"])]
    dispatch_tool("record_practice", {"text": "huis", "kind": "word", "translation": "house", "outcome": "correct"}, log)
    store.save_log(log)

    items = TestClient(app).get("/api/sessions/dave/progress").json()["items"]
    assert [(i["text"], i["score"]) for i in items] == [("huis", 100), ("werk", None), ("kantoor", None)]
