"""Tests for jarvis.stt.server.WhisperServer (written before implementation)."""

import subprocess
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from jarvis.stt.base import SttUnavailable
from jarvis.stt.server import WhisperServer


class FakeProc:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.ignore_terminate = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout or 0.0)
        return self.returncode


class FakePopen:
    def __init__(self, dead_after_first: bool = False, first_dead: bool = False) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.procs: list[FakeProc] = []
        self.dead_after_first = dead_after_first
        self.first_dead = first_dead

    def __call__(self, args: list[str], **kwargs: Any) -> FakeProc:
        self.calls.append((args, kwargs))
        proc = FakeProc(pid=100 + len(self.procs))
        if (self.first_dead and not self.procs) or (self.dead_after_first and self.procs):
            proc.returncode = 1
        self.procs.append(proc)
        return proc


def make_transport(
    texts: list[str] | None = None,
    health: str = "ok",
    status: int = 200,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/health":
            return httpx.Response(200, json={"status": health})
        if request.method == "POST" and request.url.path == "/inference":
            if status != 200:
                return httpx.Response(status, json={"error": "failed to process audio"})
            text = texts[counter["n"]] if texts else ""
            counter["n"] += 1
            return httpx.Response(200, json={"text": text})
        return httpx.Response(404)

    return httpx.MockTransport(handler), requests


def make_server(
    popen: FakePopen,
    transport: httpx.MockTransport,
    startup_timeout_s: float = 0.5,
) -> WhisperServer:
    server = WhisperServer(
        model_path=Path("ggml-base.en.bin"),
        server_bin=Path("whisper-server"),
        popen=popen,
        transport=transport,
    )
    server.poll_interval_s = 0.0
    server.startup_timeout_s = startup_timeout_s
    return server


def test_should_launch_child_with_correct_args_when_starting() -> None:
    popen = FakePopen()
    transport, _ = make_transport()
    server = make_server(popen, transport)

    server.start()

    args, kwargs = popen.calls[0]
    assert isinstance(args, list)
    assert all(isinstance(a, str) for a in args)
    assert args[0] == "whisper-server"
    assert "-m" in args
    assert args[args.index("-m") + 1] == "ggml-base.en.bin"
    assert "--host" in args
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert "-t" in args
    assert args[args.index("-t") + 1] == "4"
    assert "--port" in args
    assert args[args.index("--port") + 1].isdigit()
    assert kwargs.get("shell", False) is False
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_should_send_multipart_without_prompt_when_prompt_is_none() -> None:
    popen = FakePopen()
    transport, requests = make_transport(texts=["hello"])
    server = make_server(popen, transport)

    server.transcribe(np.zeros(1600, dtype=np.int16))

    body = requests[1].content
    assert b'name="file"' in body
    assert b"utterance.wav" in body
    assert b"RIFF" in body
    assert b'name="language"' in body
    assert b'name="language"\r\n\r\nen' in body
    assert b'name="response_format"' in body
    assert b'name="response_format"\r\n\r\njson' in body
    assert b'name="prompt"' not in body


def test_should_send_prompt_part_when_prompt_given() -> None:
    popen = FakePopen()
    transport, requests = make_transport(texts=["hello"])
    server = make_server(popen, transport)

    server.transcribe(np.zeros(1600, dtype=np.int16), prompt="Jarvis")

    body = requests[1].content
    assert b'name="prompt"' in body
    assert b"Jarvis" in body


def test_should_clean_transcript_and_set_engine_when_transcribing() -> None:
    popen = FakePopen()
    transport, _ = make_transport(texts=[" Jarvis, open Teams. "])
    server = make_server(popen, transport)

    result = server.transcribe(np.zeros(1600, dtype=np.int16))

    assert result.text == "Jarvis, open Teams."
    assert result.engine == "whisper.cpp/base.en"
    assert result.seconds >= 0


def test_should_clean_blank_audio_when_server_returns_blank() -> None:
    popen = FakePopen()
    transport, _ = make_transport(texts=[" [BLANK_AUDIO]"])
    server = make_server(popen, transport)

    result = server.transcribe(np.zeros(1600, dtype=np.int16))

    assert result.text == ""


def test_should_reuse_child_when_warm() -> None:
    popen = FakePopen()
    transport, _ = make_transport(texts=["a", "b"])
    server = make_server(popen, transport)

    server.transcribe(np.zeros(1600, dtype=np.int16))
    server.transcribe(np.zeros(1600, dtype=np.int16))

    assert len(popen.calls) == 1


def test_should_restart_once_when_child_died() -> None:
    popen = FakePopen()
    transport, _ = make_transport(texts=["a", "b"])
    server = make_server(popen, transport)

    server.transcribe(np.zeros(1600, dtype=np.int16))
    popen.procs[0].returncode = 1

    result = server.transcribe(np.zeros(1600, dtype=np.int16))

    assert result.text == "b"
    assert len(popen.calls) == 2


def test_should_raise_when_restart_also_fails() -> None:
    popen = FakePopen(dead_after_first=True)
    transport, _ = make_transport(texts=["a"])
    server = make_server(popen, transport)

    server.transcribe(np.zeros(1600, dtype=np.int16))
    popen.procs[0].returncode = 1

    with pytest.raises(SttUnavailable) as exc_info:
        server.transcribe(np.zeros(1600, dtype=np.int16))

    assert "STT_UNAVAILABLE" in str(exc_info.value)


def test_should_raise_http_error_without_restart_when_500() -> None:
    popen = FakePopen()
    transport, _ = make_transport(texts=["a"], status=500)
    server = make_server(popen, transport)

    with pytest.raises(SttUnavailable) as exc_info:
        server.transcribe(np.zeros(1600, dtype=np.int16))

    assert "HTTP 500" in str(exc_info.value)
    assert len(popen.calls) == 1


def test_should_restart_once_on_transport_error_then_fail() -> None:
    popen = FakePopen()

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(failing_handler)
    server = make_server(popen, transport)

    with pytest.raises(SttUnavailable):
        server.transcribe(np.zeros(1600, dtype=np.int16))

    assert len(popen.calls) == 2


def test_should_raise_when_startup_times_out() -> None:
    popen = FakePopen()
    transport, _ = make_transport(health="loading model")
    server = make_server(popen, transport, startup_timeout_s=0.0)

    with pytest.raises(SttUnavailable) as exc_info:
        server.start()

    assert "did not become ready" in str(exc_info.value)
    assert popen.procs[0].terminated


def test_should_raise_when_child_exits_during_startup() -> None:
    popen = FakePopen(first_dead=True)
    transport, _ = make_transport()
    server = make_server(popen, transport)

    with pytest.raises(SttUnavailable) as exc_info:
        server.start()

    assert "exited during startup" in str(exc_info.value)


def test_should_terminate_and_kill_when_close() -> None:
    popen = FakePopen()
    transport, _ = make_transport()
    server = make_server(popen, transport)

    server.start()
    assert server.pid == popen.procs[0].pid

    server.close()
    assert popen.procs[0].terminated
    assert server.pid is None

    server.close()


def test_should_kill_after_timeout_when_terminate_ignored() -> None:
    popen = FakePopen()
    transport, _ = make_transport()
    server = make_server(popen, transport)

    server.start()
    popen.procs[0].ignore_terminate = True

    server.close()

    assert popen.procs[0].killed
    assert popen.procs[0].terminated


def test_should_start_and_close_when_context_manager() -> None:
    popen = FakePopen()
    transport, _ = make_transport()
    server = make_server(popen, transport)

    with server:
        assert server.pid is not None

    assert popen.procs[0].terminated


def test_should_raise_when_response_body_has_no_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    server = make_server(FakePopen(), httpx.MockTransport(handler))

    with pytest.raises(SttUnavailable, match="malformed"):
        server.transcribe(np.zeros(1600, dtype=np.int16))
