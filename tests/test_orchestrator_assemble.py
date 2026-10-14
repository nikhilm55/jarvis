"""Tests for jarvis.orchestrator.assemble (the parts that need no model or hardware)."""

import os
import subprocess
from typing import Any

import pytest

from jarvis.orchestrator import assemble


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_should_start_whisper_server_in_its_own_session_and_die_with_us(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_popen(*args: Any, **kwargs: Any) -> None:
        seen.update(kwargs)

    marker = object()
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(assemble, "parent_death_preexec", lambda: marker)

    assemble._popen(["whisper-server"], stdin=subprocess.DEVNULL)

    assert seen == {"start_new_session": True, "preexec_fn": marker, "stdin": subprocess.DEVNULL}
