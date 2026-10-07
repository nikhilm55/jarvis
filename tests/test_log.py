import json
import logging
from collections.abc import Iterator

import pytest

from jarvis import paths
from jarvis.log import get_logger, redact


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
