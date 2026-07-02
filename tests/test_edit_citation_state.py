from src.mcp.server import edit_citation_state, _clear_edit_state


def test_clear_edit_state_clears_citation_state():
    edit_citation_state["sid"] = {"phase": "candidates_listed", "candidates": []}
    _clear_edit_state("sid")
    assert "sid" not in edit_citation_state


def test_clear_edit_state_idempotent():
    _clear_edit_state("nonexistent")
    # 不抛异常即通过
