"""Speech to text: the `Transcriber` protocol and the warm whisper.cpp server."""

from jarvis.stt.base import SttUnavailable, Transcriber, Transcript, find_server_bin

__all__ = ["SttUnavailable", "Transcriber", "Transcript", "find_server_bin"]
