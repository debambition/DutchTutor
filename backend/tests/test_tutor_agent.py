from app.agent.session_memory import SessionStore
from app.agent.tools import dispatch_tool
from app.agent.tutor_agent import TutorAgent
from app.llm.base import LLMProvider, LLMResponse, ToolCall
from app.schemas import LearningLog


class ScriptedLLMProvider(LLMProvider):
    """Replays a fixed sequence of responses, so the tool-calling loop can be
    tested deterministically without a real model."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    def chat(self, messages, tools=None) -> LLMResponse:
        return self._responses.pop(0)


def test_dispatch_tool_updates_skill_level(tmp_path):
    log = LearningLog(user_id="dave")
    result = dispatch_tool("update_skill_level", {"skill": "speaking", "level": "A2"}, log)
    assert result.startswith("ok")
    assert log.levels.speaking == "A2"


def test_dispatch_tool_moves_vocabulary_between_buckets(tmp_path):
    log = LearningLog(user_id="dave")
    dispatch_tool("log_vocabulary", {"word": "huis", "status": "struggling"}, log)
    assert "huis" in log.vocabulary.struggling

    dispatch_tool("log_vocabulary", {"word": "huis", "status": "known"}, log)
    assert "huis" in log.vocabulary.known
    assert "huis" not in log.vocabulary.struggling


def test_tutor_agent_handle_message_executes_tool_then_replies(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    tool_call_response = LLMResponse(
        text=None,
        tool_calls=[ToolCall(id="call_1", name="update_skill_level", arguments={"skill": "speaking", "level": "A2"})],
        raw_message={"role": "assistant", "tool_calls": []},
    )
    final_response = LLMResponse(text="Goed zo! Je spreekt al A2.", tool_calls=[], raw_message={})
    llm = ScriptedLLMProvider([tool_call_response, final_response])

    agent = TutorAgent(llm=llm, store=store)
    reply = agent.handle_message("erin", "Ik woon in Amsterdam.")

    assert reply == "Goed zo! Je spreekt al A2."
    saved = store.get_log("erin")
    assert saved.levels.speaking == "A2"
    assert len(saved.current_conversation) == 2  # user + assistant turn
