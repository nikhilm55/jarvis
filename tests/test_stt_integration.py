import os
from pathlib import Path

import numpy as np
import pytest

from jarvis import models
from jarvis.stt import Transcript, WhisperServer
from tests.audio_utils import silence, voice

_OUTER_HOME = os.environ.get("JARVIS_HOME")
_SERVER = os.environ.get("JARVIS_WHISPER_SERVER")


@pytest.mark.model
def test_should_transcribe_a_synthetic_clip_with_the_real_whisper_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if _SERVER is None:
        pytest.skip("set JARVIS_WHISPER_SERVER to run this test")
    if _OUTER_HOME is None:
        pytest.skip("set JARVIS_HOME to a cache holding whisper-tiny.en to run this test")
    monkeypatch.setenv("JARVIS_HOME", _OUTER_HOME)
    if not models.is_cached(models.get_spec("whisper-tiny.en")):
        pytest.skip("whisper-tiny.en is not cached; run `jarvis models fetch whisper-tiny.en`")

    with WhisperServer(models.ensure("whisper-tiny.en"), Path(_SERVER)) as server:
        audio = np.concatenate([silence(0.5), voice(1.5), silence(0.5)])
        result = server.transcribe(audio, prompt="Jarvis")
        assert isinstance(result, Transcript)
        assert isinstance(result.text, str)
        assert result.engine == "whisper.cpp/tiny.en"
        assert result.seconds > 0

        silence_clip = silence(1.0)
        silence_result = server.transcribe(silence_clip)
        assert isinstance(silence_result, Transcript)
        assert isinstance(silence_result.text, str)
