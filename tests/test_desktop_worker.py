"""Tests for the desktop worker (JSON-line protocol)."""

import io
import json
import subprocess
import sys
from typing import Any

import pytest

from jarvis.desktop.backend import DesktopBackend, Hooks
from jarvis.desktop.volume import VolumeError
from jarvis.desktop.worker import serve


def _backend(runner: Any = None) -> DesktopBackend:
    return DesktopBackend(
        Hooks(
            runner=runner or (lambda _argv: "Volume: 0.40\n"),
            entries=lambda: [],
            windows=lambda: [],
            closer=lambda _i: None,
            launcher=lambda _a: None,
            sleep=lambda _s: None,
        )
    )


def _run(backend: DesktopBackend, *lines: str) -> list[dict[str, Any]]:
    out = io.StringIO()
    serve(backend, lines, out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_should_return_ok_when_valid_volume_get() -> None:
    backend = _backend()
    result = _run(backend, json.dumps({"id": 7, "op": "volume_get", "args": {}}))
    assert result == [{"id": 7, "ok": True, "result": {"percent": 40, "muted": False}}]


def test_should_return_ok_when_args_omitted() -> None:
    backend = _backend()
    result = _run(backend, json.dumps({"id": 1, "op": "volume_get"}))
    assert result[0]["ok"] is True


def test_should_return_error_when_unknown_op() -> None:
    backend = _backend()
    result = _run(backend, json.dumps({"id": 3, "op": "nope"}))
    assert result[0]["ok"] is False
    assert result[0]["error"]["code"] == "INTERNAL"
    assert result[0]["error"]["message"] == "unknown op 'nope'"
    assert result[0]["id"] == 3


def test_should_recover_when_malformed_json() -> None:
    backend = _backend()
    result = _run(backend, "not json", json.dumps({"id": 2, "op": "volume_get"}))
    assert result[0]["id"] is None
    assert result[1]["ok"] is True


@pytest.mark.parametrize(
    "line",
    [
        "[1,2]",
        '{"op":"volume_get"}',
        '{"id":true,"op":"volume_get"}',
        '{"id":1,"op":5}',
        '{"id":1,"op":"volume_get","args":[1]}',
        "[" * 100000,
    ],
)
def test_should_return_malformed_when_bad_shape(line: str) -> None:
    backend = _backend()
    result = _run(backend, line)
    assert result[0]["ok"] is False
    assert result[0]["error"]["message"] == "malformed request"
    if line.startswith('{"id":1,'):
        assert result[0]["id"] == 1
    else:
        assert result[0]["id"] is None


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("volume_set", {"pct": "40"}),
        ("volume_set", {"pct": True}),
        ("volume_set", {}),
        ("mute", {"on": "yes"}),
        ("open_app", {"query": 5}),
    ],
)
def test_should_return_internal_when_bad_argument_types(op: str, args: dict[str, Any]) -> None:
    backend = _backend()
    result = _run(backend, json.dumps({"id": 1, "op": op, "args": args}))
    assert result[0]["ok"] is False
    assert result[0]["error"]["code"] == "INTERNAL"
    assert "bad argument" in result[0]["error"]["message"]


def test_should_return_internal_when_backend_raises(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _backend()
    calls: list[int] = [0]

    def boom() -> dict[str, Any]:
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("kaboom")
        return {"percent": 40, "muted": False}

    monkeypatch.setattr(backend, "volume_get", boom)
    result = _run(
        backend,
        json.dumps({"id": 1, "op": "volume_get"}),
        json.dumps({"id": 2, "op": "volume_get"}),
    )
    assert result[0]["ok"] is False
    assert result[0]["error"]["message"] == "unexpected error"
    assert result[1]["ok"] is True
    assert "RuntimeError" in capsys.readouterr().err


def test_should_return_timeout_when_volume_error() -> None:
    def runner(_argv: list[str]) -> str:
        raise VolumeError("TIMEOUT", "t")

    backend = _backend(runner=runner)
    result = _run(backend, json.dumps({"id": 1, "op": "volume_get"}))
    assert result[0]["error"]["code"] == "TIMEOUT"


def test_should_produce_no_output_when_blank_lines() -> None:
    backend = _backend()
    result = _run(backend, "", "   ", "\n")
    assert result == []


class _FlushCounter(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def flush(self) -> None:
        self.count += 1
        super().flush()


def test_should_flush_after_every_response() -> None:
    backend = _backend()
    out = _FlushCounter()
    serve(backend, [json.dumps({"id": 1, "op": "volume_get"})], out)
    assert out.count == 1


def test_should_round_trip_non_ascii_query() -> None:
    backend = _backend()
    line = json.dumps({"id": 1, "op": "open_app", "args": {"query": "कैलकुलेटर"}})
    result = _run(backend, line)
    assert result[0]["ok"] is False
    assert result[0]["error"]["code"] == "NOT_FOUND"
    assert "कैलकुलेटर" in result[0]["error"]["message"]


def test_should_run_worker_subprocess_for_mixed_lines() -> None:
    input_text = json.dumps({"id": 1, "op": "nope"}) + "\nnot json\n"
    proc = subprocess.run(
        [sys.executable, "-m", "jarvis.desktop.worker"],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == 1
    assert json.loads(lines[1])["id"] is None


def test_should_not_import_policy_module() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, jarvis.desktop.worker; assert 'jarvis.policy' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
