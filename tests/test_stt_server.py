"""Tests for jarvis.stt.server.WhisperServer (written before implementation)."""

import subprocess
from pathlib import Path
from typing import Any

import httpx
import numpy as np

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
