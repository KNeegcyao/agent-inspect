"""插桩模块开关测试(spec interception.插桩模块开关)。"""
from agent_inspect.interceptor.langchain_patcher import LangChainPatcher
from agent_inspect.interceptor.openai_patcher import OpenAIPatcher
from agent_inspect.session import Session


def make(instrument=None, tmp_path=None):
    return Session(
        db_path=str(tmp_path / "i.db") if tmp_path else None,
        autostart_browser=False,
        instrument=instrument,
    )


def _types(session):
    return {type(p) for p in session._patchers}


def test_default_enables_all(tmp_path):
    """未声明 instrument → 全部启用,行为与既有版本一致(spec 默认全启用)。"""
    s = make(None, tmp_path)
    try:
        assert _types(s) == {LangChainPatcher, OpenAIPatcher}
    finally:
        s.stop()


def test_langchain_disabled(tmp_path):
    """仅启用 openai:LangChain 的包装入口保持原样(未被替换)。"""
    before = __import__("langchain_core").language_models.chat_models.BaseChatModel.invoke
    s = make({"langchain": False, "openai": True}, tmp_path)
    try:
        assert _types(s) == {OpenAIPatcher}
        after = __import__("langchain_core").language_models.chat_models.BaseChatModel.invoke
        assert after is before, "停用的模块不得替换包装入口"
    finally:
        s.stop()


def test_openai_disabled(tmp_path):
    """仅启用 langchain:OpenAI 不插桩。"""
    s = make({"langchain": True, "openai": False}, tmp_path)
    try:
        assert _types(s) == {LangChainPatcher}
    finally:
        s.stop()


def test_mixed_and_unknown_keys(tmp_path):
    """混合配置独立生效;未知键忽略(与默认一致)。"""
    s = make({"langchain": False, "openai": False, "unknown": False}, tmp_path)
    try:
        assert _types(s) == set()
    finally:
        s.stop()
    s2 = make({"bogus": False}, tmp_path)
    try:
        assert _types(s2) == {LangChainPatcher, OpenAIPatcher}
    finally:
        s2.stop()


def test_stop_uninstalls(tmp_path):
    """stop 后包装卸载(既有行为不回归)。"""
    import langchain_core.language_models.chat_models as cm

    before = cm.BaseChatModel.invoke
    s = make(None, tmp_path)
    s.stop()
    assert cm.BaseChatModel.invoke is before
