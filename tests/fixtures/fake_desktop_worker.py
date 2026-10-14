"""Fake desktop worker for tests: echoes ops, simulates crash/hang/error modes."""

import json
import os
import sys
import time


def _append(path: str, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _reply(req_id: int, op: str, args: dict[str, object]) -> None:
    payload = {
        "id": req_id,
        "ok": True,
        "result": {"op": op, "args": args, "pid": os.getpid()},
    }
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _handle(req: dict[str, object], mode: str, state_dir: str) -> None:
    req_id = req.get("id")
    op = req.get("op")
    args = req.get("args")
    if isinstance(req_id, int) and isinstance(op, str) and isinstance(args, dict):
        _append(os.path.join(state_dir, "requests.txt"), op)
        if mode == "ok":
            _reply(req_id, op, args)
        elif mode == "crash_once":
            flag = os.path.join(state_dir, "crashed")
            if not os.path.exists(flag):
                with open(flag, "w", encoding="utf-8"):
                    pass
                os._exit(1)
            _reply(req_id, op, args)
        elif mode == "crash_always":
            os._exit(1)
        elif mode == "hang":
            time.sleep(60)
        elif mode == "slow":
            time.sleep(0.5)
            _reply(req_id, op, args)
        elif mode == "error":
            sys.stdout.write(
                json.dumps(
                    {
                        "id": req_id,
                        "ok": False,
                        "error": {"code": "NOT_FOUND", "message": "nope"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
        elif mode == "garbage":
            sys.stdout.write("this is not json\n")
            sys.stdout.flush()
        elif mode == "stale":
            sys.stdout.write(json.dumps({"id": req_id + 1000, "ok": True, "result": {}}) + "\n")
            sys.stdout.flush()
            _reply(req_id, op, args)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
    state_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    _append(os.path.join(state_dir, "starts.txt"), "start")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(req, dict):
            _handle(req, mode, state_dir)


if __name__ == "__main__":
    main()
