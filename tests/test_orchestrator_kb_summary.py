# tests/test_orchestrator_kb_summary.py
from unittest.mock import patch
from src.agents.intent import IntentAgent
from src.agents.orchestrator import OrchestratorAgent


def test_orchestrator_injects_kb_summary_to_intent():
    """process_message 应把 kb_summary 塞进 session_context，传给 IntentAgent。"""
    captured = {}

    class FakeIntentAgent:
        def analyze(self, user_message, session_context, message_history):
            captured["kb_summary"] = (session_context or {}).get("kb_summary")
            # 返回一个最小 IntentResult 替身
            from src.agents.intent import IntentResult, IntentType, WorkflowMode
            return IntentResult(
                intent=IntentType.GREETING, workflow_mode=WorkflowMode.NONE,
                confidence=1.0, reasoning="test", extracted_topic=None,
            )

    with patch("src.core.kb_context.build_kb_directory_summary",
               return_value="系统知识库：1 个分类 / 5 篇论文。分类：rag(5)。"):
        orch = OrchestratorAgent()
        orch.intent_agent = FakeIntentAgent()
        orch.process_message("你好", session_id="sid", session_context={})
    assert "rag(5)" in captured["kb_summary"]


def test_intent_prompt_contains_kb_summary_placeholder():
    """INTENT_ANALYZE_PROMPT 必须含 {kb_summary} 占位。"""
    from src.agents.prompts import INTENT_ANALYZE_PROMPT
    assert "{kb_summary}" in INTENT_ANALYZE_PROMPT
