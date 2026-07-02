"""报告编辑功能单元测试。

覆盖：
- _resolve_output_file 路径穿越防护
- _is_completion_message 完成意图识别
- _find_section_span 章节定位
- _apply_edit_sections EDIT SECTION 解析与应用
- _try_init_edit_from_message 编辑会话自动初始化
- POST /api/outputs/write 原子写入（通过 TestClient）
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_server(monkeypatch, tmp_path):
    """用临时 DATA_DIR 启动 server，避免污染真实 data 目录。"""
    tmp_data = tmp_path / "data"
    tmp_data.mkdir()
    (tmp_data / "outputs").mkdir()

    monkeypatch.setenv("DATA_DIR", str(tmp_data))
    # 强制重新导入，使模块级 DATA_DIR 取新值
    for mod in list(sys.modules.keys()):
        if mod == "src.mcp.server" or mod.startswith("src.mcp.server."):
            del sys.modules[mod]
    import src.mcp.server as srv

    # 把 outputs 目录挂上去，供测试直接读写文件
    srv.DATA_DIR = tmp_data
    yield srv
    # 清理编辑状态，避免跨用例污染
    srv.edit_target_files.clear()
    srv.working_copies.clear()


# ==================== 路径穿越防护 ====================

class TestResolveOutputFile:
    def test_rejects_dotdot(self, isolated_server):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            isolated_server._resolve_output_file("../etc/passwd")
        assert exc.value.status_code == 403

    def test_rejects_absolute_path(self, isolated_server):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            isolated_server._resolve_output_file("/etc/passwd")

    def test_rejects_slash_in_filename(self, isolated_server):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            isolated_server._resolve_output_file("subdir/file.md")
        assert exc.value.status_code == 403

    def test_rejects_nonexistent_file(self, isolated_server):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            isolated_server._resolve_output_file("notexist.md")
        assert exc.value.status_code == 404

    def test_accepts_existing_file(self, isolated_server):
        f = isolated_server.DATA_DIR / "outputs" / "report.md"
        f.write_text("hello", encoding="utf-8")
        resolved = isolated_server._resolve_output_file("report.md")
        assert resolved == f.resolve()


# ==================== 完成意图识别 ====================

class TestCompletionDetection:
    @pytest.mark.parametrize("msg", ["完成", "结束", "可以了", "没问题了", "就这样", "done", "finished"])
    def test_exact_completion(self, isolated_server, msg):
        assert isolated_server._is_completion_message(msg) is True

    @pytest.mark.parametrize("msg", [
        "全部完成", "写回吧", "就这样吧", "可以了，写回", "保存并结束",
    ])
    def test_phrase_completion(self, isolated_server, msg):
        assert isolated_server._is_completion_message(msg) is True

    @pytest.mark.parametrize("msg", [
        "请修改第三节", "这个章节完成了",  # 含"完成"但非整句
        "我觉得可以再调整一下", "继续修改",
    ])
    def test_non_completion(self, isolated_server, msg):
        assert isolated_server._is_completion_message(msg) is False


# ==================== 章节定位 ====================

class TestFindSectionSpan:
    SAMPLE = """# 报告标题

## 1. 引言
引言内容。

## 2. 方法
方法内容第一段。
方法内容第二段。

### 2.1 子方法
子方法内容。

## 3. 结论
结论内容。
"""

    def test_finds_h2_section(self, isolated_server):
        span = isolated_server._find_section_span(self.SAMPLE, "## 2. 方法")
        assert span is not None
        start, end = span
        assert self.SAMPLE[start:].startswith("## 2. 方法")
        # end 应指向 "## 3. 结论" 之前
        assert self.SAMPLE[end:].startswith("## 3. 结论")

    def test_finds_subsection_with_higher_level_terminator(self, isolated_server):
        span = isolated_server._find_section_span(self.SAMPLE, "### 2.1 子方法")
        assert span is not None
        start, end = span
        assert self.SAMPLE[start:].startswith("### 2.1 子方法")
        assert self.SAMPLE[end:].startswith("## 3. 结论")

    def test_returns_none_for_missing_header(self, isolated_server):
        assert isolated_server._find_section_span(self.SAMPLE, "## 99. 不存在") is None

    def test_returns_none_for_invalid_header_format(self, isolated_server):
        assert isolated_server._find_section_span(self.SAMPLE, "不是标题") is None


# ==================== EDIT SECTION 应用 ====================

class TestApplyEditSections:
    WORKING = """# 报告

## 1. 引言
旧引言。

## 2. 方法
旧方法。
"""

    def test_replaces_single_section(self, isolated_server):
        reply = """我修改了第 1 节。

<!-- EDIT SECTION: ## 1. 引言 -->
## 1. 引言
新引言内容。
<!-- /EDIT SECTION -->
"""
        new, warnings = isolated_server._apply_edit_sections(self.WORKING, reply)
        assert warnings == []
        assert "新引言内容" in new
        assert "旧引言" not in new
        # 第 2 节应保留
        assert "## 2. 方法" in new
        assert "旧方法" in new

    def test_multiple_sections(self, isolated_server):
        reply = """修改了两节。

<!-- EDIT SECTION: ## 1. 引言 -->
## 1. 引言
新引言。
<!-- /EDIT SECTION -->

<!-- EDIT SECTION: ## 2. 方法 -->
## 2. 方法
新方法。
<!-- /EDIT SECTION -->
"""
        new, warnings = isolated_server._apply_edit_sections(self.WORKING, reply)
        assert warnings == []
        assert "新引言" in new and "新方法" in new
        assert "旧引言" not in new and "旧方法" not in new

    def test_warning_for_missing_header(self, isolated_server):
        reply = """<!-- EDIT SECTION: ## 99. 不存在 -->
## 99. 不存在
内容。
<!-- /EDIT SECTION -->
"""
        new, warnings = isolated_server._apply_edit_sections(self.WORKING, reply)
        assert new == self.WORKING  # 不变更
        assert len(warnings) == 1
        assert "不存在" in warnings[0]

    def test_warning_for_no_edit_blocks(self, isolated_server):
        new, warnings = isolated_server._apply_edit_sections(self.WORKING, "我没改任何东西")
        assert new == self.WORKING
        assert len(warnings) == 1


# ==================== 编辑会话初始化 ====================

class TestTryInitEdit:
    def test_initializes_from_report_tag(self, isolated_server):
        # 先创建目标文件
        target = isolated_server.DATA_DIR / "outputs" / "report.md"
        target.write_text("# 真实文件内容", encoding="utf-8")

        msg = "请帮我编辑以下报告（文件：report.md）。读完后请问我怎么改：\n\n<report>\n# 工作副本\n\n正文\n</report>"
        err = isolated_server._try_init_edit_from_message("sess-1", msg)
        assert err is None
        assert "sess-1" in isolated_server.edit_target_files
        assert "# 工作副本" in isolated_server.working_copies["sess-1"]
        isolated_server._clear_edit_state("sess-1")

    def test_returns_error_when_filename_missing(self, isolated_server):
        msg = "<report>内容</report>"
        err = isolated_server._try_init_edit_from_message("sess-2", msg)
        assert err is not None
        assert "目标文件名" in err or "文件" in err
        assert "sess-2" not in isolated_server.edit_target_files

    def test_returns_error_when_file_not_exist(self, isolated_server):
        msg = "（文件：notexist.md）\n<report>内容</report>"
        err = isolated_server._try_init_edit_from_message("sess-3", msg)
        assert err is not None
        assert "sess-3" not in isolated_server.edit_target_files

    def test_returns_none_for_non_edit_message(self, isolated_server):
        assert isolated_server._try_init_edit_from_message("sess-4", "普通聊天消息") is None


# ==================== 写文件 API（TestClient）====================

class TestWriteOutputAPI:
    def test_write_overwrites_existing_file(self, isolated_server):
        from fastapi.testclient import TestClient as _TC
        client = _TC(isolated_server.app)
        f = isolated_server.DATA_DIR / "outputs" / "writable.md"
        f.write_text("old content", encoding="utf-8")

        res = client.post("/api/outputs/write", json={
            "filename": "writable.md", "content": "new content"
        })
        assert res.status_code == 200
        assert res.json()["ok"] is True
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_rejects_path_traversal(self, isolated_server):
        from fastapi.testclient import TestClient as _TC
        client = _TC(isolated_server.app)
        res = client.post("/api/outputs/write", json={
            "filename": "../evil.md", "content": "x"
        })
        assert res.status_code == 403

    def test_write_rejects_nonexistent_file(self, isolated_server):
        from fastapi.testclient import TestClient as _TC
        client = _TC(isolated_server.app)
        res = client.post("/api/outputs/write", json={
            "filename": "ghost.md", "content": "x"
        })
        assert res.status_code == 404

    def test_write_atomic_on_failure_preserves_original(self, isolated_server, monkeypatch):
        from fastapi.testclient import TestClient as _TC
        client = _TC(isolated_server.app)
        f = isolated_server.DATA_DIR / "outputs" / "atomic.md"
        f.write_text("original", encoding="utf-8")

        # 让 os.replace 抛错，验证原文件不变
        import src.mcp.server as srv
        def boom(*a, **kw):
            raise OSError("simulated")
        monkeypatch.setattr(srv.os, "replace", boom)
        res = client.post("/api/outputs/write", json={
            "filename": "atomic.md", "content": "should not apply"
        })
        assert res.status_code == 500
        assert f.read_text(encoding="utf-8") == "original"
