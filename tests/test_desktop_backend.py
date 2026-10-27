"""Tests for the desktop backend (open/close apps, volume, launch)."""

import contextlib
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.desktop.apps import AppEntry
from jarvis.desktop.backend import (
    DesktopBackend,
    Hooks,
    WorkerError,
    configured_aliases,
    launch_app,
)
from jarvis.desktop.x11 import WindowInfo, X11Error
from tests.x_fake import FakeX


def _app(name: str, wm_class: str) -> AppEntry:
    return AppEntry(
        desktop_id=f"org.example.{name}.desktop",
        name=name,
        generic_name="",
        keywords=(),
        exec_line=name.lower(),
        startup_wm_class=wm_class,
        path=Path(f"/x/{name}.desktop"),
    )


def _win(wid: int, cls: str) -> WindowInfo:
    return WindowInfo(wid, "i", cls, 1, "t")


class _Seq:
    def __init__(self, *lists: list[WindowInfo]) -> None:
        self._lists = lists
        self.calls = 0

    def __call__(self) -> list[WindowInfo]:
        idx = self.calls
        self.calls += 1
        if idx < len(self._lists):
            return self._lists[idx]
        return self._lists[-1]


def _hooks(**kw: Any) -> Hooks:
    defaults: dict[str, Any] = {
        "entries": lambda: [_app("Calculator", "ExampleCalc")],
        "windows": _Seq([]),
        "closer": lambda _i: None,
        "launcher": lambda _a: None,
        "runner": lambda _argv: "Volume: 0.40\n",
        "sleep": lambda _s: None,
        "port": lambda: contextlib.nullcontext(FakeX()),  # never the real display
    }
    defaults.update(kw)
    return Hooks(**defaults)


def test_should_return_new_window_ids_when_matching_window_appears() -> None:
    calls: list[float] = []
    windows = _Seq(
        [_win(9, "Other")],
        [_win(9, "Other"), _win(3, "Other")],
        [_win(9, "Other"), _win(3, "Other"), _win(2, "ExampleCalc")],
    )
    launched: list[AppEntry] = []
    backend = DesktopBackend(
        _hooks(
            windows=windows,
            launcher=launched.append,
            sleep=calls.append,
        )
    )
    result = backend.open_app("calculator")
    assert result == {"app": "Calculator", "window_ids_new": [2]}
    assert len(launched) == 1
    assert calls.count(0.1) == 1


def test_should_return_empty_when_no_matching_window_ever() -> None:
    windows = _Seq([_win(9, "Other")])
    sleeps: list[float] = []
    backend = DesktopBackend(_hooks(windows=windows, sleep=sleeps.append))
    result = backend.open_app("calculator")
    assert result["window_ids_new"] == []
    assert windows.calls == 41
    assert len(sleeps) == 39


def test_should_raise_not_found_when_no_entries() -> None:
    backend = DesktopBackend(_hooks(entries=lambda: []))
    with pytest.raises(WorkerError) as exc:
        backend.open_app("calculator")
    assert exc.value.code == "NOT_FOUND"


def test_should_raise_ambiguous_when_two_candidates() -> None:
    backend = DesktopBackend(
        _hooks(entries=lambda: [_app("Terminal One", "A"), _app("Terminal Two", "B")])
    )
    with pytest.raises(WorkerError) as exc:
        backend.open_app("terminal")
    assert exc.value.code == "AMBIGUOUS"
    assert "Terminal One" in exc.value.message
    assert "Terminal Two" in exc.value.message


def test_should_close_only_matching_windows() -> None:
    closed: list[int] = []
    backend = DesktopBackend(
        _hooks(
            windows=lambda: [_win(1, "ExampleCalc"), _win(2, "ExampleCalc"), _win(3, "Other")],
            closer=closed.append,
        )
    )
    result = backend.close_app("calculator")
    assert result == {"app": "Calculator", "closed": 2}
    assert closed == [1, 2]


def test_should_skip_not_found_and_propagate_internal() -> None:
    def closer(wid: int) -> None:
        if wid == 1:
            raise X11Error("NOT_FOUND", "gone")
        if wid == 2:
            raise X11Error("INTERNAL", "x")

    backend = DesktopBackend(
        _hooks(
            windows=lambda: [_win(1, "ExampleCalc"), _win(2, "ExampleCalc")],
            closer=closer,
        )
    )
    with pytest.raises(X11Error) as exc:
        backend.close_app("calculator")
    assert exc.value.code == "INTERNAL"


def _runner(argv: Sequence[str]) -> str:
    return "Volume: 0.40\n"


@pytest.mark.parametrize(
    ("op", "args", "expected_argv"),
    [
        ("volume_get", (), ["get-volume", "@DEFAULT_AUDIO_SINK@"]),
        ("volume_set", (50,), ["set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "0.50"]),
        ("volume_step", (5,), ["set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"]),
        ("mute", (True,), ["set-mute", "@DEFAULT_AUDIO_SINK@", "1"]),
    ],
)
def test_should_return_volume_state_when_op_runs(
    op: str, args: tuple[object, ...], expected_argv: list[str]
) -> None:
    seen: list[list[str]] = []

    def runner(argv: Sequence[str]) -> str:
        seen.append(list(argv))
        return "Volume: 0.40\n"

    backend = DesktopBackend(_hooks(runner=runner))
    result = getattr(backend, op)(*args)
    assert result == {"percent": 40, "muted": False}
    assert seen[0] == expected_argv


class _FakePopen:
    returncode = 0

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs

    def wait(self, timeout: float | None = None) -> None:
        pass


def test_should_launch_app_with_gio(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> _FakePopen:
        captured.append((list(argv), kwargs))
        return _FakePopen(argv, **kwargs)

    monkeypatch.setattr("jarvis.desktop.backend.subprocess.Popen", fake_popen)
    launch_app(_app("Calculator", "ExampleCalc"))
    argv, kwargs = captured[0]
    assert argv == ["gio", "launch", str(Path("/x/Calculator.desktop"))]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert "shell" not in kwargs


def test_should_raise_internal_when_gio_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailPopen(_FakePopen):
        returncode = 1

    monkeypatch.setattr("jarvis.desktop.backend.subprocess.Popen", _FailPopen)
    with pytest.raises(WorkerError) as exc:
        launch_app(_app("Calculator", "ExampleCalc"))
    assert exc.value.code == "INTERNAL"


def test_should_raise_unsupported_when_gio_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_kw: Any) -> None:
        raise FileNotFoundError("no gio")

    monkeypatch.setattr("jarvis.desktop.backend.subprocess.Popen", boom)
    with pytest.raises(WorkerError) as exc:
        launch_app(_app("Calculator", "ExampleCalc"))
    assert exc.value.code == "UNSUPPORTED_ON_PLATFORM"


def test_should_return_none_when_gio_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SlowPopen(_FakePopen):
        def wait(self, timeout: float | None = None) -> None:
            raise subprocess.TimeoutExpired("gio", 5)

    monkeypatch.setattr("jarvis.desktop.backend.subprocess.Popen", _SlowPopen)
    launch_app(_app("Calculator", "ExampleCalc"))


def test_should_resolve_a_spoken_alias_before_fuzzy_matching() -> None:
    entries = [_app("Calculator", "ExampleCalc"), _app("Maths", "Maths")]
    backend = DesktopBackend(
        _hooks(entries=lambda: entries, aliases=lambda: {"sums": "org.example.Maths.desktop"})
    )
    assert backend.open_app("sums")["app"] == "Maths"


def test_should_list_installed_apps_by_name_with_their_source() -> None:
    backend = DesktopBackend(_hooks(entries=lambda: [_app("Zed", "z"), _app("alpha", "a")]))
    assert backend.list_apps() == {
        "apps": [
            {"name": "alpha", "id": "org.example.alpha.desktop", "source": "desktop"},
            {"name": "Zed", "id": "org.example.Zed.desktop", "source": "desktop"},
        ]
    }


def test_should_report_whether_an_app_has_a_window_open() -> None:
    windows = [_win(1, "ExampleCalc"), _win(2, "ExampleCalc"), _win(3, "Other")]
    backend = DesktopBackend(_hooks(windows=lambda: windows))
    assert backend.is_running("calculator") == {
        "app": "Calculator",
        "running": True,
        "windows": 2,
        "installed": True,
    }
    none_open = DesktopBackend(_hooks(windows=lambda: [_win(3, "Other")]))
    assert none_open.is_running("calculator")["running"] is False


def test_should_judge_an_app_that_is_not_installed_by_its_window_class() -> None:
    backend = DesktopBackend(_hooks(windows=lambda: [_win(7, "Zoom")]))
    assert backend.is_running("zoom") == {
        "app": "zoom",
        "running": True,
        "windows": 1,
        "installed": False,
    }
    assert backend.is_running("skype")["running"] is False


def test_should_not_hide_an_ambiguous_name_when_asked_if_it_is_running() -> None:
    entries = [_app("Terminal One", "T1"), _app("Terminal Two", "T2")]
    with pytest.raises(WorkerError) as info:
        DesktopBackend(_hooks(entries=lambda: entries)).is_running("terminal")
    assert info.value.code == "AMBIGUOUS"


def test_should_read_aliases_from_the_settings_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text("[apps.aliases]\nteams = 'x.desktop'\n", encoding="utf-8")
    monkeypatch.setattr("jarvis.config.config_dir", lambda: config)
    assert configured_aliases() == {"teams": "x.desktop"}


def test_should_ignore_aliases_when_the_settings_file_is_broken(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text("not = [valid", encoding="utf-8")
    monkeypatch.setattr("jarvis.config.config_dir", lambda: config)
    assert configured_aliases() == {}
    assert "ignoring app aliases" in capsys.readouterr().err
