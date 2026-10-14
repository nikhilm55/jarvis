import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "acceptance_m1", ROOT / "scripts" / "acceptance_m1.py"
)
assert spec and spec.loader
m1 = importlib.util.module_from_spec(spec)
sys.modules["acceptance_m1"] = m1
spec.loader.exec_module(m1)


def test_should_render_markdown_table_when_results_are_present() -> None:
    result = m1.IdleResult(
        label="silence",
        frames=10,
        segments=0,
        wall_s=1.0,
        cpu_s=0.05,
        percent=5.0,
    )
    table = m1.idle_table([result])
    assert "| silence |" in table
    assert "5.0" in table
