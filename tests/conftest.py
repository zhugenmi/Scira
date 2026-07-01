"""Pytest 共享配置。

integration 标记的测试默认跳过（需要真实网络或运行中的后端）。
显式启用：`pytest --run-integration` 或 `pytest -m integration`。
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="运行标记为 integration 的测试（默认跳过）",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = pytest.mark.skip(reason="integration 测试，需 --run-integration 启用")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
