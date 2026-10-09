from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from subradar.models import SourceConfig

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Vienna")


@pytest.fixture
def src() -> SourceConfig:
    return SourceConfig(name="Testhalle", city="Linz", url="https://venue.example/")


class FakeMessages:
    """Stands in for anthropic.Anthropic().messages — returns canned tool input."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        data = self.responder(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=data)])


@pytest.fixture
def fake_claude(tmp_path):
    from subradar.ai import Claude

    def make(responder):
        msgs = FakeMessages(responder)
        return Claude(tmp_path / "cache", model="test", client=SimpleNamespace(messages=msgs)), msgs

    return make


@pytest.fixture
def project(tmp_path) -> Path:
    """A copy of the project config and web app in a temp folder."""
    for name in ("sources.yaml", "taste.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "web", tmp_path / "web")
    (tmp_path / "feedback").mkdir()
    return tmp_path
