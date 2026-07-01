"""验证下载进度计数：paper_callback 应收到 (paper_id, status, error, title)。"""
from unittest.mock import patch, MagicMock
from src.agents.reader import ReaderAgent, ReadingTask


def test_paper_callback_receives_title_and_status():
    """paper_callback 签名为 (paper_id, status, error, title)。"""
    captured = []
    agent = ReaderAgent(
        max_workers=1,
        paper_callback=lambda pid, st, err, title=None: captured.append((pid, st, err, title)),
    )

    task = ReadingTask(paper_id="p1", title="My Paper", authors=[], abstract="", pdf_url="")

    # patch download_paper to skip real network; mark downloaded→completed
    def fake_download(t, download_dir=None):
        t.status = "completed"
        return t

    with patch.object(agent, "download_paper", side_effect=fake_download), \
         patch.object(agent, "parse_paper", side_effect=lambda t: t), \
         patch.object(agent, "extract_structured_info", side_effect=lambda t: t):
        agent.process_batch([task])

    # 应该至少捕获 downloading + success
    statuses = [c[1] for c in captured]
    assert "downloading" in statuses
    assert "success" in statuses
    # 所有捕获都应带 title
    for pid, st, err, title in captured:
        assert pid == "p1"
        assert title == "My Paper"
