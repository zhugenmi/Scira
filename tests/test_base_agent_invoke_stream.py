"""验证 invoke_stream 逐 token 回调并返回完整字符串。"""
from unittest.mock import MagicMock
from src.agents.base import BaseAgent


def test_invoke_stream_calls_callback_per_chunk():
    agent = BaseAgent.__new__(BaseAgent)
    agent.system_prompt = "sys"
    agent.config = MagicMock()
    agent.config.model.model_name = "test-model"

    fake_chunk1 = MagicMock(); fake_chunk1.content = "Hello "
    fake_chunk2 = MagicMock(); fake_chunk2.content = "world"
    agent.llm = MagicMock()
    agent.llm.stream.return_value = iter([fake_chunk1, fake_chunk2])

    tokens = []
    result = agent.invoke_stream("hi", token_callback=tokens.append)
    assert result == "Hello world"
    assert tokens == ["Hello ", "world"]
