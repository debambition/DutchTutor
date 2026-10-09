from app.agent.session_memory import SessionStore
from app.schemas import LearningLog


def test_new_user_gets_default_log(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("alice")
    assert log.user_id == "alice"
    assert log.levels.speaking == "A1"
    assert log.vocabulary.known == []


def test_save_and_reload_roundtrip(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = store.get_log("bob")
    log.levels.speaking = "A2"
    log.vocabulary.known.append("hallo")
    store.save_log(log)

    reloaded = store.get_log("bob")
    assert reloaded.levels.speaking == "A2"
    assert reloaded.vocabulary.known == ["hallo"]


def test_log_is_independent_pydantic_model(tmp_path):
    store = SessionStore(data_dir=tmp_path)
    log = LearningLog(user_id="carol")
    store.save_log(log)
    assert (tmp_path / "carol.json").exists()
