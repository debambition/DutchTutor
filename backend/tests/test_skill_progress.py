from app.agent.progress import skill_progress
from app.agent.session_memory import SessionStore
from app.agent.tools import dispatch_tool
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProvider, LLMResponse
from app.schemas import LearningLog


def practise(log, text, skill, *outcomes):
    for outcome in outcomes:
        dispatch_tool("record_practice", {"text": text, "kind": "word", "translation": "-", "outcome": outcome, "skill": skill}, log)


def by_skill(log):
    return {p.skill: p for p in skill_progress(log)}


def test_attempts_are_tagged_with_skill_and_current_level():
    log = LearningLog(user_id="dave")
    log.levels.speaking = "A2"
    practise(log, "huis", "speaking", "correct", "incorrect")
    assert [(a.skill, a.level, a.correct) for a in log.practice_items[0].history] == [
        ("speaking", "A2", True),
        ("speaking", "A2", False),
    ]


def test_strong_items_need_two_attempts_and_80_percent():
    log = LearningLog(user_id="dave")
    practise(log, "huis", "speaking", "correct", "correct")  # strong
    practise(log, "kat", "speaking", "correct")  # only one attempt
    practise(log, "hond", "speaking", "correct", "incorrect")  # 50%
    practise(log, "boom", "writing", "correct", "correct")  # different skill

    speaking = by_skill(log)["speaking"]
    assert (speaking.level, speaking.next_level) == ("A1", "A2")
    assert (speaking.strong_items, speaking.target, speaking.percent) == (1, 20, 5)
    assert (speaking.attempts, speaking.accuracy) == (5, 80)
    assert by_skill(log)["writing"].strong_items == 1
    assert by_skill(log)["listening"].accuracy is None


def test_progress_restarts_after_level_up():
    log = LearningLog(user_id="dave")
    practise(log, "huis", "speaking", "correct", "correct")
    dispatch_tool("update_skill_level", {"skill": "speaking", "level": "A2"}, log)

    speaking = by_skill(log)["speaking"]
    assert (speaking.level, speaking.next_level, speaking.strong_items, speaking.target) == ("A2", "B1", 0, 40)


def test_progress_caps_at_100_and_top_level_has_no_next():
    log = LearningLog(user_id="dave")
    for i in range(25):
        practise(log, f"woord{i}", "reading", "correct", "correct")
    log.levels.writing = "C2"

    assert by_skill(log)["reading"].percent == 100
    assert by_skill(log)["writing"].next_level is None


class RecordingLLMProvider(LLMProvider):
    def __init__(self) -> None:
        self.messages = []

    def chat(self, messages, tools=None) -> LLMResponse:
        self.messages = list(messages)
        return LLMResponse(text="ok", tool_calls=[], raw_message={"role": "assistant", "content": "ok"})


def test_tutor_is_told_channel_and_readiness(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("dave")
    for i in range(20):
        practise(log, f"woord{i}", "speaking", "correct", "correct")
    store.save_log(log)
    llm = RecordingLLMProvider()

    TutorAgent(llm=llm, store=store).handle_message("dave", "Ik woon in Utrecht.", channel="voice")

    contents = [m["content"] for m in llm.messages]
    assert any("spoke this aloud" in c for c in contents)
    assert any("ready to move up in: speaking (A1 -> A2)" in c for c in contents)


def test_production_skill_follows_how_the_message_arrived():
    log = LearningLog(user_id="dave")
    args = {"text": "huis", "kind": "word", "translation": "house", "outcome": "correct"}
    dispatch_tool("record_practice", {**args, "skill": "speaking"}, log, channel="text")
    dispatch_tool("record_practice", {**args, "skill": "writing"}, log, channel="voice")
    dispatch_tool("record_practice", {**args, "skill": "listening"}, log, channel="text")
    assert [a.skill for a in log.practice_items[0].history] == ["writing", "speaking", "listening"]
