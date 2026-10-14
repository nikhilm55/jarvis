"""Log files and their directory are readable by the owner only, like the activity log."""

import logging
import logging.handlers
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis import paths
from jarvis.log import audit, get_logger

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX modes")


@pytest.fixture(autouse=True)
def _detach_handlers() -> Iterator[None]:
    yield
    for name in ("jarvis", "jarvis.audit"):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _flush_handlers(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        handler.flush()


def test_should_set_owner_only_modes_when_logging_first_time() -> None:
    logger = get_logger("jarvis.x")
    logger.info("hello")
    _flush_handlers(logging.getLogger("jarvis"))

    logs_dir = paths.data_dir() / "logs"
    log_file = logs_dir / "jarvisd.jsonl"

    assert _mode(logs_dir) == 0o700
    assert _mode(log_file) == 0o600


def test_should_create_audit_file_with_owner_only_mode_when_audit_called() -> None:
    audit("policy", "decision", tool="t")

    logs_dir = paths.data_dir() / "logs"
    audit_file = logs_dir / "audit.jsonl"

    assert _mode(audit_file) == 0o600


def test_should_tighten_existing_loose_modes_when_files_pre_exist() -> None:
    logs_dir = paths.data_dir() / "logs"
    logs_dir.mkdir(parents=True)
    os.chmod(logs_dir, 0o755)  # noqa: S103 - the loose mode an older run would have left

    jarvis_file = logs_dir / "jarvisd.jsonl"
    audit_file = logs_dir / "audit.jsonl"
    jarvis_file.write_text("", encoding="utf-8")
    audit_file.write_text("", encoding="utf-8")
    os.chmod(jarvis_file, 0o644)
    os.chmod(audit_file, 0o644)

    logger = get_logger("jarvis.x")
    logger.info("hi")
    _flush_handlers(logging.getLogger("jarvis"))
    audit("policy", "d")

    assert _mode(logs_dir) == 0o700
    assert _mode(jarvis_file) == 0o600
    assert _mode(audit_file) == 0o600


def test_should_keep_owner_only_modes_when_rollover_occurs() -> None:
    logger = get_logger("jarvis.x")
    jarvis_logger = logging.getLogger("jarvis")

    handler: logging.handlers.RotatingFileHandler | None = None
    for h in jarvis_logger.handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            handler = h
            break
    assert handler is not None

    handler.maxBytes = 200
    for _ in range(20):
        logger.info("x" * 50)
    _flush_handlers(jarvis_logger)

    logs_dir = paths.data_dir() / "logs"
    live_file = logs_dir / "jarvisd.jsonl"
    backup_file = logs_dir / "jarvisd.jsonl.1"

    assert backup_file.exists()
    assert _mode(backup_file) == 0o600
    assert _mode(live_file) == 0o600
