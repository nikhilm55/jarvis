"""Tests for jarvis.desktop.volume."""

import subprocess
from collections.abc import Sequence

import pytest

from jarvis.desktop.volume import (
    SINK,
    VolumeError,
    VolumeState,
    parse_volume,
    run_wpctl,
    set_mute,
    volume_get,
    volume_set,
    volume_step,
)


class FakeWpctl:
    """A callable matching Runner that records calls and returns canned output."""

    def __init__(self, get_text: str = "Volume: 0.40\n") -> None:
        self.get_text = get_text
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if args and args[0] == "get-volume":
            return self.get_text
        return ""


def test_should_parse_volume_when_plain() -> None:
    state = parse_volume("Volume: 0.82")
    assert state == VolumeState(percent=82, muted=False)


def test_should_parse_muted_when_flag_present() -> None:
    state = parse_volume("Volume: 0.40 [MUTED]")
    assert state == VolumeState(percent=40, muted=True)


def test_should_parse_full_when_one() -> None:
    state = parse_volume("Volume: 1.00")
    assert state == VolumeState(percent=100, muted=False)


def test_should_parse_zero_when_empty() -> None:
    state = parse_volume("Volume: 0.00")
    assert state == VolumeState(percent=0, muted=False)


def test_should_round_when_fractional() -> None:
    state = parse_volume("Volume: 0.37")
    assert state.percent == 37


def test_should_strip_when_whitespace() -> None:
    state = parse_volume("  Volume: 0.82  \n")
    assert state == VolumeState(percent=82, muted=False)


def test_should_raise_internal_when_garbage() -> None:
    with pytest.raises(VolumeError) as exc:
        parse_volume("hello world")
    assert exc.value.code == "INTERNAL"


def test_should_raise_internal_when_empty() -> None:
    with pytest.raises(VolumeError) as exc:
        parse_volume("")
    assert exc.value.code == "INTERNAL"


def test_should_get_volume_when_called() -> None:
    fake = FakeWpctl("Volume: 0.82\n")
    state = volume_get(runner=fake)
    assert state == VolumeState(percent=82, muted=False)
    assert fake.calls == [["get-volume", SINK]]


def test_should_set_volume_when_normal() -> None:
    fake = FakeWpctl("Volume: 0.40\n")
    state = volume_set(40, runner=fake)
    assert state == VolumeState(percent=40, muted=False)
    assert fake.calls == [
        ["set-volume", "-l", "1.0", SINK, "0.40"],
        ["get-volume", SINK],
    ]


def test_should_clamp_when_above() -> None:
    fake = FakeWpctl("Volume: 1.00\n")
    volume_set(150, runner=fake)
    assert fake.calls[0][4] == "1.00"


def test_should_clamp_when_below() -> None:
    fake = FakeWpctl("Volume: 0.00\n")
    volume_set(-5, runner=fake)
    assert fake.calls[0][4] == "0.00"


def test_should_raise_when_float() -> None:
    fake = FakeWpctl()
    with pytest.raises(VolumeError) as exc:
        volume_set(40.5, runner=fake)  # type: ignore[arg-type]
    assert exc.value.code == "INTERNAL"
    assert fake.calls == []


def test_should_raise_when_bool() -> None:
    fake = FakeWpctl()
    with pytest.raises(VolumeError) as exc:
        volume_set(True, runner=fake)
    assert exc.value.code == "INTERNAL"
    assert fake.calls == []


def test_should_raise_when_string() -> None:
    fake = FakeWpctl()
    with pytest.raises(VolumeError) as exc:
        volume_set("40", runner=fake)  # type: ignore[arg-type]
    assert exc.value.code == "INTERNAL"
    assert fake.calls == []


def test_should_step_up_when_positive() -> None:
    fake = FakeWpctl("Volume: 0.45\n")
    volume_step(5, runner=fake)
    assert fake.calls[0][4] == "5%+"


def test_should_step_down_when_negative() -> None:
    fake = FakeWpctl("Volume: 0.30\n")
    volume_step(-10, runner=fake)
    assert fake.calls[0][4] == "10%-"


def test_should_only_get_when_zero() -> None:
    fake = FakeWpctl("Volume: 0.40\n")
    volume_step(0, runner=fake)
    assert fake.calls == [["get-volume", SINK]]


def test_should_clamp_step_when_large() -> None:
    fake = FakeWpctl("Volume: 1.00\n")
    volume_step(500, runner=fake)
    assert fake.calls[0][4] == "100%+"


def test_should_mute_when_true() -> None:
    fake = FakeWpctl("Volume: 0.40 [MUTED]\n")
    state = set_mute(True, runner=fake)
    assert state.muted is True
    assert fake.calls[0] == ["set-mute", SINK, "1"]


def test_should_unmute_when_false() -> None:
    fake = FakeWpctl("Volume: 0.40\n")
    state = set_mute(False, runner=fake)
    assert state.muted is False
    assert fake.calls[0] == ["set-mute", SINK, "0"]


def test_should_raise_when_mute_non_bool() -> None:
    fake = FakeWpctl()
    with pytest.raises(VolumeError) as exc:
        set_mute(1, runner=fake)  # type: ignore[arg-type]
    assert exc.value.code == "INTERNAL"
    assert fake.calls == []


def test_should_propagate_error_when_runner_fails() -> None:
    def bad_runner(args: Sequence[str]) -> str:
        raise VolumeError("TIMEOUT", "wpctl timed out")

    with pytest.raises(VolumeError) as exc:
        volume_get(runner=bad_runner)
    assert exc.value.code == "TIMEOUT"


def test_should_raise_unsupported_when_file_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("wpctl not found")

    monkeypatch.setattr("jarvis.desktop.volume.subprocess.run", fake_run)
    with pytest.raises(VolumeError) as exc:
        run_wpctl(["get-volume", SINK])
    assert exc.value.code == "UNSUPPORTED_ON_PLATFORM"


def test_should_raise_timeout_when_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="wpctl", timeout=3)

    monkeypatch.setattr("jarvis.desktop.volume.subprocess.run", fake_run)
    with pytest.raises(VolumeError) as exc:
        run_wpctl(["get-volume", SINK])
    assert exc.value.code == "TIMEOUT"


def test_should_raise_internal_when_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = subprocess.CompletedProcess[str](
        args=["wpctl"], returncode=1, stdout="", stderr="some error here"
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return result

    monkeypatch.setattr("jarvis.desktop.volume.subprocess.run", fake_run)
    with pytest.raises(VolumeError) as exc:
        run_wpctl(["get-volume", SINK])
    assert exc.value.code == "INTERNAL"
    assert exc.value.message.startswith("wpctl failed:")


def test_should_return_stdout_when_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        args: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured["args"] = list(args)
        captured["encoding"] = kwargs.get("encoding")
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess[str](
            args=list(args), returncode=0, stdout="Volume: 0.82\n", stderr=""
        )

    monkeypatch.setattr("jarvis.desktop.volume.subprocess.run", fake_run)
    result = run_wpctl(["get-volume", SINK])
    assert result == "Volume: 0.82\n"
    assert captured["args"] == ["wpctl", "get-volume", SINK]
    assert captured["encoding"] == "utf-8"
    assert captured["timeout"] == 3
