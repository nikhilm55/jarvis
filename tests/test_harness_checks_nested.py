"""Nested-import pruning in the test lock: unused nested imports may go, used ones may not."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("harness_checks", ROOT / "scripts/harness_checks.py")
assert spec and spec.loader
hc = importlib.util.module_from_spec(spec)
sys.modules["harness_checks"] = hc
spec.loader.exec_module(hc)

LOCKED = """import pytest


def test_a(tmp_path):
    import os
    from x import y, z
    assert y(os.sep) == z
    with pytest.raises(ValueError):
        y(-1)


class TestB:
    def test_b(self):
        import json
        assert json.dumps(1) == "1"


def test_c():
    def inner():
        import re
        from q import r
        return r(1)
    assert inner() == 1
"""

ALLOWED = {
    "unused import re removed from inner": LOCKED.replace("        import re\n", ""),
    "unused nested import added to test_a": LOCKED.replace(
        "    import os\n", "    import os\n    import sys\n"
    ),
    "from q import r gains an unused name": LOCKED.replace(
        "        from q import r\n", "        from q import r, unused_name\n"
    ),
}

FLAGGED = {
    "used import os removed from test_a": LOCKED.replace("    import os\n", ""),
    "from x import y, z loses z": LOCKED.replace(
        "    from x import y, z\n", "    from x import y\n"
    ),
    "used import json removed from test_b": LOCKED.replace("        import json\n", ""),
    "from q import r removed from inner": LOCKED.replace("        from q import r\n", ""),
    "import os renamed to import os as o": LOCKED.replace(
        "    import os\n", "    import os as o\n"
    ),
}

LOCK_MODES = [{}, {"extend": True}, {"annotations": True}]


@pytest.mark.parametrize("flags", LOCK_MODES)
@pytest.mark.parametrize("name", ALLOWED)
def test_should_allow_a_nested_unused_import_to_go_in_every_lock_mode(
    name: str, flags: dict[str, bool]
) -> None:
    new = ALLOWED[name]
    assert new != LOCKED
    assert hc.lock_violations(LOCKED, new, **flags) == []


@pytest.mark.parametrize("flags", LOCK_MODES)
@pytest.mark.parametrize("name", FLAGGED)
def test_should_still_flag_a_nested_import_that_is_used_in_every_lock_mode(
    name: str, flags: dict[str, bool]
) -> None:
    new = FLAGGED[name]
    assert new != LOCKED
    assert hc.lock_violations(LOCKED, new, **flags)


SIDE_EFFECT = """def test_a():
    import jarvis.strict_mode{noqa}
    assert 1
"""


@pytest.mark.parametrize("flags", LOCK_MODES)
@pytest.mark.parametrize("noqa", ["  # noqa", "  # noqa: F401"])
def test_should_never_let_a_nested_noqa_import_go(noqa: str, flags: dict[str, bool]) -> None:
    locked = SIDE_EFFECT.format(noqa=noqa)
    new = locked.replace(f"    import jarvis.strict_mode{noqa}\n", "")
    assert new != locked
    assert hc.lock_violations(locked, new, **flags)


@pytest.mark.parametrize("flags", LOCK_MODES)
@pytest.mark.parametrize("noqa", ["", "  # noqa: E402"])
def test_should_let_an_unused_nested_import_go_unless_noqa_keeps_it_from_ruff(
    noqa: str, flags: dict[str, bool]
) -> None:
    locked = SIDE_EFFECT.format(noqa=noqa)
    new = locked.replace(f"    import jarvis.strict_mode{noqa}\n", "")
    assert hc.lock_violations(locked, new, **flags) == []
