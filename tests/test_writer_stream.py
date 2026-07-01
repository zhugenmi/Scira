"""验证 WriterAgent.write_section 流式回调被触发。"""
from unittest.mock import MagicMock
from src.agents.writer import WriterAgent, PaperSection


def test_write_section_invokes_stream_callback():
    agent = WriterAgent.__new__(WriterAgent)
    agent.config = MagicMock()
    agent.config.model.model_name = "test"
    agent.llm = MagicMock()
    agent.llm.stream.return_value = iter([MagicMock(content="chunk1"), MagicMock(content="chunk2")])

    section = PaperSection(section_id="s1", title="Intro")
    captured = []
    result = agent.write_section(
        section,
        {"global_knowledge": {}, "writing_style": "academic", "reference_list": []},
        stream_callback=lambda sid, t, tok: captured.append((sid, t, tok)),
    )

    assert "chunk1chunk2" in result.content
    assert captured == [("s1", "Intro", "chunk1"), ("s1", "Intro", "chunk2")]
