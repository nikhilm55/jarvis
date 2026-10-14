"""Structured JSON-lines logging to `data_dir()/logs/jarvisd.jsonl`, with secrets masked."""

import json
import logging
import os
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from jarvis.paths import data_dir, ensure

_ROOT = "jarvis"
_FILE = "jarvisd.jsonl"
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


def _attach_handler(root: logging.Logger) -> None:
    target = os.path.abspath(ensure(data_dir() / "logs") / _FILE)
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            if handler.baseFilename == target:
                return
            handler.close()  # JARVIS_HOME moved: follow it
            root.removeHandler(handler)
    handler = RotatingFileHandler(target, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """A logger under the `jarvis` namespace; the file handler is attached once, on that root."""
    root = logging.getLogger(_ROOT)
    root.setLevel(logging.INFO)
    _attach_handler(root)
    return logging.getLogger(name if name.partition(".")[0] == _ROOT else f"{_ROOT}.{name}")
