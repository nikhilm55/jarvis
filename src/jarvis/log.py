"""Structured JSON-lines logging to `data_dir()/logs/jarvisd.jsonl`, with secrets masked."""

import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from io import TextIOWrapper
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.paths import data_dir, ensure

_ROOT = "jarvis"
_FILE = "jarvisd.jsonl"
_AUDIT_FILE = "audit.jsonl"
_AUDIT_LOGGER = "jarvis.audit"
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}

_URL_CREDENTIALS = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_API_KEY = re.compile(
    r"\bsk-[A-Za-z0-9_-]{16,}|\bgsk_[A-Za-z0-9]{16,}|\bghp_[A-Za-z0-9]{20,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}|\bAKIA[0-9A-Z]{16}\b"
)
_KEYED_SECRET = re.compile(
    r"((?:key|token|secret|password)\s*=\s*)[\"']?[A-Za-z0-9+/_=-]{16,}[\"']?", re.IGNORECASE
)


def redact(text: str) -> str:
    """Mask URL credentials, bearer tokens, API-key shapes and `key=`/`token=` secrets."""
    text = _URL_CREDENTIALS.sub(r"\1***@", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _API_KEY.sub("***", text)
    return _KEYED_SECRET.sub(r"\1***", text)


def _clean(value: object) -> object:
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact(str(value))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "name": record.name,
            "msg": redact(record.getMessage()),
        }
        entry.update({k: _clean(v) for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False)


class _PrivateFileHandler(RotatingFileHandler):
    """A rotating file only its owner can read (0600), like the activity log."""

    def _open(self) -> TextIOWrapper:
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.chmod(self.baseFilename, 0o600)  # a file made by an older run keeps no looser bits
        return open(fd, "a", encoding=self.encoding, errors=self.errors)


def _logs_dir() -> Path:
    directory = ensure(data_dir() / "logs")
    os.chmod(directory, 0o700)
    return directory


class _AuditHandler(_PrivateFileHandler):
    """Unlike the app handler, write, rollover and format errors propagate to the caller."""

    def handleError(self, record: logging.LogRecord) -> None:
        error = sys.exception()  # the exception emit() is handling
        if error is not None:
            raise error


def _attach_handler(root: logging.Logger) -> None:
    target = os.path.abspath(_logs_dir() / _FILE)
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            if handler.baseFilename == target:
                return
            handler.close()  # JARVIS_HOME moved: follow it
            root.removeHandler(handler)
    handler = _PrivateFileHandler(target, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def _audit_handler() -> _AuditHandler:
    logger = logging.getLogger(_AUDIT_LOGGER)
    logger.propagate = False
    target = os.path.abspath(_logs_dir() / _AUDIT_FILE)
    for handler in logger.handlers:
        if isinstance(handler, _AuditHandler):
            if handler.baseFilename == target:
                return handler
            handler.close()  # JARVIS_HOME moved: follow it
            logger.removeHandler(handler)
    handler = _AuditHandler(target, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    return handler


def audit(source: str, message: str, **fields: object) -> None:
    """Append one record to the audit log (`audit.jsonl`); any failure raises.

    Goes straight to the handler, so `logging.disable()` and logger levels cannot silence it.
    Callers that must not act without an audit trail (the policy gate) treat a raise as a deny.
    """
    record = logging.LogRecord(
        name=f"jarvis.{source}",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in fields.items():
        if key in _STANDARD:
            raise ValueError(f"reserved audit field {key!r}")
        setattr(record, key, value)
    _audit_handler().handle(record)


def get_logger(name: str) -> logging.Logger:
    """A logger under the `jarvis` namespace; the file handler is attached once, on that root."""
    root = logging.getLogger(_ROOT)
    root.setLevel(logging.INFO)
    _attach_handler(root)
    return logging.getLogger(name if name.partition(".")[0] == _ROOT else f"{_ROOT}.{name}")
