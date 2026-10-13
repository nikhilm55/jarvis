"""Tests for jarvis.orchestrator.timing."""

from jarvis.config import AudioSettings, BrainSettings, Settings
from jarvis.orchestrator.timing import Timing


def test_should_use_the_documented_defaults_when_built_plainly() -> None:
    timing = Timing()
    assert (timing.listen_window_s, timing.reply_window_s) == (5.0, 8.0)
    assert (timing.thinking_after_s, timing.deaf_tail_s) == (1.2, 0.3)
    assert timing.min_silence_ms == 400


def test_should_follow_the_settings_when_built_from_them() -> None:
    settings = Settings(
        audio=AudioSettings(trailing_ms=900), brain=BrainSettings(inactivity_reset_s=60)
    )
    timing = Timing.from_settings(settings)
    assert timing.trailing_s == 0.9
    assert timing.inactivity_reset_s == 60.0
    assert timing.reply_window_s == 8.0
