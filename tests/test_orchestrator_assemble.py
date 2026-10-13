"""Tests for jarvis.orchestrator.assemble (the parts that need no model or hardware)."""

import functools
import os

import pytest

from jarvis.orchestrator import assemble


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-only")
def test_should_start_whisper_server_in_its_own_process_group() -> None:
    assert isinstance(assemble._POPEN, functools.partial)
    assert assemble._POPEN.keywords == {"start_new_session": True}
