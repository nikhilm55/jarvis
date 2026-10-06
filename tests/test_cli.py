import pytest

from jarvis import __version__
from jarvis.cli import main


def test_should_print_version_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"jarvis {__version__}"


def test_should_exit_cleanly_when_run_without_arguments() -> None:
    assert main([]) == 0
