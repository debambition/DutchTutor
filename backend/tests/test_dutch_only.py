"""Only Dutch is evaluated; the intake captures languages and the learner's
chosen explanation language."""
from app.agent.pronunciation import dutch_pronunciation
from app.agent.session_memory import SessionStore
from app.agent.tools import dispatch_tool
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProvider, LLMResponse
from app.schemas import LearningLog
from app.speech.base import Pronunciation
from app.speech.language_segments import EXPLANATION, DUTCH, dutch_words, looks_non_dutch, split_by_language


def practise(log, text, outcome="correct"):
    return dispatch_tool(
        "record_practice",
        {"text": text, "kind": "word", "translation": "", "outcome": outcome, "skill": "speaking"},
        log,
    )


def test_intake_answers_and_english_are_not_tracked_as_practice():
    log = LearningLog(user_id="dave")
    for text in ("Hindi", "not", "Not sure.", "I live in Utrecht", "मेरा नाम"):
        assert practise(log, text).startswith("error:"), text
    assert log.practice_items == []


def test_plain_dutch_vocabulary_is_still_tracked():
    log = LearningLog(user_id="dave")
    for text in ("huis", "Ik woon in Utrecht.", "Goed, dank je."):
        assert practise(log, text).startswith("ok:"), text
    assert len(log.practice_items) == 3


def test_language_detection():
    assert looks_non_dutch("Hindi") and looks_non_dutch("Not sure.")
    assert not looks_non_dutch("huis")
    assert dutch_words("My name is Goro, ik heet Goro.") == {"ik", "heet", "goro"}
    assert dutch_words("Hindi.") == set()
    assert split_by_language('"Ik heet Goro" का मतलब है') == [(DUTCH, '"Ik heet Goro"'), (EXPLANATION, "का मतलब है")]


def test_pronunciation_is_dropped_for_non_dutch_and_filtered_for_mixed():
    log = LearningLog(user_id="dave")
    english = Pronunciation(overall=60, accuracy=55, fluency=90, words=[("hindi", 55)])
    assert dutch_pronunciation(english, "Hindi.", log) is None

    mixed = Pronunciation(overall=70, accuracy=70, fluency=88, words=[("my", 40), ("name", 45), ("ik", 90), ("heet", 70)])
    kept = dutch_pronunciation(mixed, "My name, ik heet.", log)
    assert kept.words == [("ik", 90), ("heet", 70)] and kept.accuracy == 80 and kept.fluency == 88


def test_profile_lists_accept_strings_and_bad_values_are_refused():
    log = LearningLog(user_id="dave")
    assert dispatch_tool("update_profile_field", {"field": "other_languages", "value": "English, Urdu"}, log).startswith("ok")
    assert log.profile.other_languages == ["English", "Urdu"]
    assert dispatch_tool("update_profile_field", {"field": "latin_script_literate", "value": "perhaps"}, log).startswith("error")
    assert log.profile.latin_script_literate is True
    LearningLog.model_validate_json(log.model_dump_json())  # still loadable


class RecordingLLM(LLMProvider):
    def __init__(self):
        self.tutor_messages = []

    def chat(self, messages, tools=None):
        if tools is not None:
            self.tutor_messages = list(messages)
        return LLMResponse(text="ok", raw_message={"role": "assistant", "content": "ok"})


def contents(llm):
    return "\n".join(m["content"] for m in llm.tutor_messages)


def test_first_session_intake_asks_languages_and_explanation_choice(tmp_path):
    llm = RecordingLLM()
    TutorAgent(llm=llm, store=SessionStore(data_dir=tmp_path)).start_session("dave")
    text = contents(llm)
    assert "other languages they speak" in text and "want explanations in" in text
    assert "Explanation language: not chosen yet" in text
    assert "never record, grade, correct or comment on the learner's English" in text


def test_chosen_explanation_language_is_used(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("dave")
    log.profile.native_languages = ["Hindi"]
    log.profile.feedback_language = "Hindi"
    store.save_log(log)
    llm = RecordingLLM()
    TutorAgent(llm=llm, store=store).handle_message("dave", "Ik heet Dave.")
    assert "Explanation language (chosen by the learner): Hindi" in contents(llm)


def test_speech_uses_voice_for_chosen_language(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.main import app
    from tests.test_enhancements import FakeSpeech

    store = SessionStore(data_dir=tmp_path)
    speech = FakeSpeech()
    monkeypatch.setattr(routes, "_store", store)
    monkeypatch.setattr(routes, "_speech", speech)
    from app import auth
    app.dependency_overrides[auth.require_signed_in] = lambda: "dave"

    http = TestClient(app)
    http.post("/api/speak", json={"text": "Hallo"})
    log = store.get_log("dave")
    log.profile.feedback_language = "Hindi"
    store.save_log(log)
    http.post("/api/speak", json={"text": "Hallo"})
    assert speech.voices == [None, "hi-IN-SwaraNeural"]


def test_introduced_items_must_appear_in_the_reply(tmp_path):
    import json

    from tests.test_enhancements import RecordingLLM, text_reply, tool_reply

    store = SessionStore(data_dir=tmp_path)
    audit = json.dumps({"graded": [], "missed": [
        {"text": "Waarom leer je Nederlands?", "kind": "sentence", "translation": "-", "outcome": "introduced", "note": ""},
        {"text": "Goedemorgen", "kind": "word", "translation": "good morning", "outcome": "introduced", "note": ""},
    ]})
    llm = RecordingLLM([
        tool_reply(
            ("record_practice", {"text": "Dank je wel!", "kind": "sentence", "translation": "धन्यवाद", "outcome": "introduced"}),
            ("record_practice", {"text": "Hoe gaat het?", "kind": "sentence", "translation": "आप कैसे हैं?", "outcome": "introduced"}),
        ),
        text_reply('धन्यवाद! अब सीखें: "Hoe gaat het?" और "Goedemorgen"।'),
        text_reply(audit),
    ])
    TutorAgent(llm=llm, store=store).handle_message("dave", "Hindi please")
    assert sorted(i.text for i in store.get_log("dave").practice_items) == ["Goedemorgen", "Hoe gaat het?"]
