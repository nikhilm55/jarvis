"""Isolated desktop-automation worker (ADR-0008).

jarvisd talks to this process with JSON lines. The worker never imports
jarvis.policy or jarvis.log.
"""

import io
import json
import sys
import traceback
from collections.abc import Iterable, Sequence
from typing import TextIO

from jarvis.desktop.backend import DesktopBackend, WorkerError
from jarvis.desktop.volume import VolumeError
from jarvis.desktop.x11 import X11Error


def _str_arg(args: dict[str, object], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise WorkerError("INTERNAL", f"bad argument {name!r}")
    return value


def _int_arg(args: dict[str, object], name: str) -> int:
    value = args.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkerError("INTERNAL", f"bad argument {name!r}")
    return value


def _bool_arg(args: dict[str, object], name: str) -> bool:
    value = args.get(name)
    if not isinstance(value, bool):
        raise WorkerError("INTERNAL", f"bad argument {name!r}")
    return value


def _opt_int_arg(args: dict[str, object], name: str) -> int | None:
    return None if args.get(name) is None else _int_arg(args, name)


def _str_list_arg(args: dict[str, object], name: str) -> list[str]:
    value = args.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise WorkerError("INTERNAL", f"bad argument {name!r}")
    return [str(v) for v in value]


def _window_op(backend: DesktopBackend, args: dict[str, object]) -> dict[str, object]:
    return backend.window_op(  # gate-ok: worker runs the op
        _str_arg(args, "ref"),
        _str_arg(args, "op"),
        _opt_int_arg(args, "monitor"),
        _str_list_arg(args, "with_refs"),
    )


def _dispatch(  # noqa: PLR0911  (a flat table of ops, one return each)
    backend: DesktopBackend, op: str, args: dict[str, object]
) -> dict[str, object]:
    if op == "open_app":
        return backend.open_app(_str_arg(args, "query"))  # gate-ok: worker runs the op
    if op == "close_app":
        return backend.close_app(_str_arg(args, "query"))  # gate-ok: worker runs the op
    if op == "list_windows":
        return backend.list_windows()  # gate-ok: worker runs the op
    if op == "focus_window":
        return backend.focus_window(_str_arg(args, "ref"))  # gate-ok: worker runs the op
    if op == "window_op":
        return _window_op(backend, args)
    if op == "list_apps":
        return backend.list_apps()  # gate-ok: worker runs the op
    if op == "is_running":
        return backend.is_running(_str_arg(args, "query"))  # gate-ok: worker runs the op
    if op == "volume_get":
        return backend.volume_get()  # gate-ok: worker runs the op
    if op == "volume_set":
        return backend.volume_set(_int_arg(args, "pct"))  # gate-ok: worker runs the op
    if op == "volume_step":
        return backend.volume_step(_int_arg(args, "delta"))  # gate-ok: worker runs the op
    if op == "mute":
        return backend.mute(_bool_arg(args, "on"))  # gate-ok: worker runs the op
    raise WorkerError("INTERNAL", f"unknown op {op!r}")


def _error(
    req_id: int | None, code: str, message: str, alternatives: Sequence[str] = ()
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if alternatives:
        error["alternatives"] = list(alternatives)
    return {"id": req_id, "ok": False, "error": error}


def _validate(request: object) -> tuple[int, str, dict[str, object]]:
    if not isinstance(request, dict):
        raise WorkerError("INTERNAL", "malformed request")
    req_id = request.get("id")
    if not isinstance(req_id, int) or isinstance(req_id, bool):
        raise WorkerError("INTERNAL", "malformed request")
    op = request.get("op")
    if not isinstance(op, str):
        raise WorkerError("INTERNAL", "malformed request")
    args = request.get("args")
    if args is None:
        args = {}
    elif not isinstance(args, dict):
        raise WorkerError("INTERNAL", "malformed request")
    return req_id, op, args


def handle_line(backend: DesktopBackend, line: str) -> dict[str, object]:
    """Parse one JSON line and run the requested op, never raising."""
    try:
        request = json.loads(line)
    except (ValueError, RecursionError):  # JSONDecodeError is a ValueError
        return _error(None, "INTERNAL", "malformed request")
    req_id = (
        request.get("id") if isinstance(request, dict) and type(request.get("id")) is int else None
    )
    try:
        _, op, args = _validate(request)
        result = _dispatch(backend, op, args)
    except (WorkerError, VolumeError, X11Error) as exc:
        return _error(req_id, exc.code, exc.message, getattr(exc, "alternatives", ()))
    except Exception:
        traceback.print_exc()
        return _error(req_id, "INTERNAL", "unexpected error")
    return {"id": req_id, "ok": True, "result": result}


def serve(backend: DesktopBackend, lines: Iterable[str], out: TextIO) -> None:
    """Read JSON lines, dispatch, and write one JSON response per line."""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        response = handle_line(backend, stripped)
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()


def main() -> None:
    """Run the worker against stdin/stdout."""
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        write_through=True,
        line_buffering=True,
    )
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol stream
    serve(DesktopBackend(), stdin, stdout)


if __name__ == "__main__":
    main()
