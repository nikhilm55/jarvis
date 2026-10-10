"""Whisper.cpp server wrapper for the Jarvis STT pipeline."""

import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, Self

import httpx

from jarvis.audio.sources import Pcm
from jarvis.log import get_logger
from jarvis.stt.base import SttUnavailable, Transcript, clean_transcript, encode_wav

logger = get_logger(__name__)

RESTART_REMEDY = "Restart Jarvis; if it keeps happening re-run the setup check for speech to text"
STARTUP_REMEDY = "Check the model file and run whisper-server by hand to see its error"


class _Process(Protocol):
    """The slice of `subprocess.Popen` this module uses (so tests can inject a fake)."""

    pid: int
    returncode: int | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


PopenFactory = Callable[..., _Process]


class WhisperServer:
    """Wraps a long-lived whisper-server child process for STT."""

    startup_timeout_s: float = 15.0
    poll_interval_s: float = 0.05

    def __init__(
        self,
        model_path: Path,
        server_bin: Path,
        threads: int = 4,
        *,
        popen: PopenFactory = subprocess.Popen,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model_path = model_path
        self._server_bin = server_bin
        self._threads = threads
        self._popen = popen
        self._transport = transport
        self._proc: _Process | None = None
        self._client: httpx.Client | None = None
        self._port: int | None = None

    @property
    def pid(self) -> int | None:
        """PID of the live child process, or None if not running."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return None

    def start(self) -> None:
        """Launch the whisper-server child and wait until it is ready."""
        if self._proc is not None:
            if self._proc.poll() is None:
                return
            # Process is dead, clean up old resources before starting new one
            self.close()
        self._launch()
        self._wait_ready()

    def transcribe(self, pcm: Pcm, prompt: str | None = None) -> Transcript:
        """Transcribe PCM audio, lazily starting the server if needed."""
        if self._proc is None or self._proc.poll() is not None:
            self.start()
        start = time.perf_counter()
        response = self._post_with_one_restart(pcm, prompt)
        if response.status_code != 200:
            raise SttUnavailable(
                f"whisper-server returned HTTP {response.status_code}",
                RESTART_REMEDY,
            )
        try:
            payload = response.json()
            text = clean_transcript(str(payload["text"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise SttUnavailable(
                "whisper-server returned a malformed response", RESTART_REMEDY
            ) from exc
        elapsed = time.perf_counter() - start
        return Transcript(text=text, engine=self._engine_name(), seconds=elapsed)

    def close(self) -> None:
        """Stop the child process and client; safe to call repeatedly."""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            self._proc = None
        self._port = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _launch(self) -> None:
        """Pick a free port and spawn the whisper-server child process."""
        self._port = self._pick_port()
        cmd = [
            str(self._server_bin),
            "-m",
            str(self._model_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(self._port),
            "-t",
            str(self._threads),
        ]
        self._proc = self._popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{self._port}",
            timeout=10.0,
            transport=self._transport,
        )
        logger.info("whisper-server started", extra={"pid": self._proc.pid})

    def _wait_ready(self) -> None:
        """Poll the health endpoint until ready or the timeout elapses."""
        deadline = time.monotonic() + self.startup_timeout_s
        while True:
            if self._proc is not None and self._proc.poll() is not None:
                code = self._proc.returncode
                self.close()
                raise SttUnavailable(
                    f"whisper-server exited during startup (code {code})",
                    STARTUP_REMEDY,
                )
            if self._health_ok():
                return
            if time.monotonic() >= deadline:
                self.close()
                raise SttUnavailable(
                    f"whisper-server did not become ready within {self.startup_timeout_s:g} s",
                    STARTUP_REMEDY,
                )
            time.sleep(self.poll_interval_s)

    def _post(self, pcm: Pcm, prompt: str | None) -> httpx.Response:
        """Send the audio to the inference endpoint and return the response."""
        if self._client is None:
            raise SttUnavailable("whisper-server is not running", RESTART_REMEDY)
        data = {"language": "en", "response_format": "json"}
        if prompt is not None:
            data["prompt"] = prompt
        return self._client.post(
            "/inference",
            files={"file": ("utterance.wav", encode_wav(pcm), "audio/wav")},
            data=data,
        )

    def _health_ok(self) -> bool:
        """Return True if the server reports status ok; False otherwise."""
        if self._client is None:
            return False
        try:
            response = self._client.get("/health")
        except httpx.TransportError:
            return False
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("status") == "ok")
        except (ValueError, AttributeError):
            return False

    def _post_with_one_restart(self, pcm: Pcm, prompt: str | None) -> httpx.Response:
        """POST once; if the child is gone, restart it once and retry once."""
        try:
            return self._post(pcm, prompt)
        except httpx.TransportError:
            logger.warning("whisper-server unreachable; restarting once")
        self.close()
        self.start()
        try:
            return self._post(pcm, prompt)
        except httpx.TransportError as error:
            raise SttUnavailable("whisper-server stopped responding", RESTART_REMEDY) from error

    def _pick_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _engine_name(self) -> str:
        return "whisper.cpp/" + self._model_path.stem.removeprefix("ggml-")
