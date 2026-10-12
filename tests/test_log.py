import errno
import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis import log as jlog
from jarvis import paths
from jarvis.log import audit, get_logger, redact


@pytest.fixture(autouse=True)
def _detach_handlers() -> Iterator[None]:
    yield
    root = logging.getLogger("jarvis")
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


HEX = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret
B64 = "c2VjcmV0c2VjcmV0c2VjcmV0=="  # pragma: allowlist secret


@pytest.mark.parametrize(
    ("secret", "text"),
    [
        ("hunter2pass", "GET https://alice:hunter2pass@example.com/x"),  # pragma: allowlist secret
        ("abc.DEF-123_token", "Authorization: Bearer abc.DEF-123_token"),
        ("sk-" + "a1B2c3D4" * 4, "key sk-" + "a1B2c3D4" * 4 + " end"),
        ("sk-ant-api03-" + "Zy9" * 10, "sk-ant-api03-" + "Zy9" * 10),
        ("gsk_" + "q" * 30, "GROQ gsk_" + "q" * 30),
        ("ghp_" + "r" * 36, "token ghp_" + "r" * 36),
        ("github_pat_" + "s" * 40, "github_pat_" + "s" * 40),
        ("AKIAABCDEFGHIJKLMNOP", "aws AKIAABCDEFGHIJKLMNOP here"),  # pragma: allowlist secret
        (HEX, f"api_key={HEX}"),
        (B64, f"password='{B64}'"),
        ("t0k3nt0k3nt0k3nt0k3n", "access_token=t0k3nt0k3nt0k3nt0k3n&x=1"),
    ],
)
def test_should_mask_secret_when_text_contains_one(secret: str, text: str) -> None:
    result = redact(text)
    assert secret not in result
    assert "***" in result


def test_should_keep_url_scheme_and_host_when_masking_credentials() -> None:
    assert redact("https://u:p@host.example/a") == "https://***@host.example/a"


def test_should_leave_ordinary_text_alone() -> None:
    text = "turn 7: opened Firefox, key=small, https://example.com/a?b=c"
    assert redact(text) == text


def test_should_be_idempotent_when_redacting_twice() -> None:
    text = "Bearer abc123 https://u:p@h/x api_key=0123456789abcdef0123 ghp_" + "x" * 36
    assert redact(redact(text)) == redact(text)


def read_lines() -> list[dict[str, object]]:
    for handler in logging.getLogger("jarvis").handlers:
        handler.flush()
    log_file = paths.data_dir() / "logs" / "jarvisd.jsonl"
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]


def test_should_write_json_lines_with_redacted_message_and_extras() -> None:
    logger = get_logger("jarvis.wake")
    logger.info("calling %s", "https://u:p@host/x", extra={"turn": 4, "auth": "Bearer tok123"})
    [line] = read_lines()
    assert line["level"] == "INFO"
    assert line["name"] == "jarvis.wake"
    assert line["msg"] == "calling https://***@host/x"
    assert line["turn"] == 4
    assert line["auth"] == "Bearer ***"
    assert isinstance(line["ts"], str)


def test_should_not_duplicate_lines_when_get_logger_is_called_repeatedly() -> None:
    for _ in range(3):
        get_logger("jarvis.a")
    get_logger("jarvis.b").info("once")
    assert len(read_lines()) == 1
    assert len(logging.getLogger("jarvis").handlers) == 1


def test_should_redact_exception_text() -> None:
    logger = get_logger("jarvis.err")
    try:
        raise RuntimeError("failed with Bearer secrettoken")
    except RuntimeError:
        logger.exception("boom")
    [line] = read_lines()
    assert "secrettoken" not in json.dumps(line)


@pytest.fixture(autouse=True)
def _detach_audit_handler() -> Iterator[None]:
    yield
    for handler in list(logging.getLogger("jarvis.audit").handlers):
        handler.close()
        logging.getLogger("jarvis.audit").removeHandler(handler)


def test_should_write_audit_record_to_audit_file_only() -> None:
    audit("policy", "policy decision", tool="t", decision="allow")

    logs = paths.data_dir() / "logs"
    audit_file = logs / "audit.jsonl"
    assert audit_file.exists()
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["name"] == "jarvis.policy"
    assert record["msg"] == "policy decision"
    assert record["tool"] == "t"
    assert record["decision"] == "allow"

    app_file = logs / "jarvisd.jsonl"
    if app_file.exists():
        app_text = app_file.read_text(encoding="utf-8")
        assert "policy decision" not in app_text


def test_should_redact_audit_values() -> None:
    audit("policy", "policy decision", header="Bearer abc.DEF-123_token")

    logs = paths.data_dir() / "logs"
    audit_file = logs / "audit.jsonl"
    text = audit_file.read_text(encoding="utf-8")
    assert "abc.DEF-123_token" not in text


def test_should_reject_reserved_audit_field() -> None:
    with pytest.raises(ValueError):
        audit("x", "m", name="boom")


def test_should_raise_when_audit_write_fails_but_app_log_swallows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _BrokenStream:
        def write(self, message: str) -> None:
            raise OSError(errno.ENOSPC, "No space left on device")

        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

        def tell(self) -> int:
            return 0

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    audit("policy", "policy decision", tool="t")
    handler = jlog._audit_handler()
    monkeypatch.setattr(handler, "stream", _BrokenStream())

    with pytest.raises(OSError):
        audit("policy", "policy decision", tool="t")

    app_logger = get_logger("jarvis.x")
    app_handler = logging.getLogger("jarvis").handlers[0]
    monkeypatch.setattr(app_handler, "stream", _BrokenStream())
    app_logger.info("still fine")  # stdlib reports to stderr and carries on
    capsys.readouterr()


def test_should_raise_when_rollover_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit("policy", "policy decision", tool="t")
    handler = jlog._audit_handler()
    monkeypatch.setattr(handler, "maxBytes", 1)

    def boom() -> None:
        raise OSError("rollover failed")

    monkeypatch.setattr(handler, "doRollover", boom)

    with pytest.raises(OSError):
        audit("policy", "policy decision", tool="t")


def test_should_raise_when_log_dir_unwritable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JARVIS_HOME", str(blocker / "home"))

    with pytest.raises(OSError):
        audit("policy", "policy decision", tool="t")


def test_should_follow_moved_jarvis_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_a = tmp_path / "home_a"
    home_b = tmp_path / "home_b"
    monkeypatch.setenv("JARVIS_HOME", str(home_a))
    audit("policy", "policy decision", tool="a")

    monkeypatch.setenv("JARVIS_HOME", str(home_b))
    audit("policy", "policy decision", tool="b")

    file_a = home_a / "data" / "logs" / "audit.jsonl"
    file_b = home_b / "data" / "logs" / "audit.jsonl"
    assert len(file_a.read_text(encoding="utf-8").splitlines()) == 1
    b_lines = file_b.read_text(encoding="utf-8").splitlines()
    assert len(b_lines) == 1
    b_record = json.loads(b_lines[0])
    assert b_record["tool"] == "b"


def test_should_audit_even_when_logging_is_disabled() -> None:
    try:
        logging.disable(logging.CRITICAL)
        audit("policy", "policy decision", tool="t")
    finally:
        logging.disable(logging.NOTSET)

    logs = paths.data_dir() / "logs"
    audit_file = logs / "audit.jsonl"
    assert audit_file.exists()
    assert len(audit_file.read_text(encoding="utf-8").splitlines()) == 1
