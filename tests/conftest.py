"""让离线测试不受开发者的模型和追踪配置影响。"""

import os

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch):
    settings_names = {name.casefold() for name in Settings.model_fields}
    for name in tuple(os.environ):
        if name.casefold() in settings_names:
            monkeypatch.delenv(name)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
