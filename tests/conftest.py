"""Keep offline tests independent of the developer's model and tracing settings."""

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
