import pytest

from jarvis import models
from jarvis.cli import main


def test_should_list_the_four_subcommands_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ("run", "say", "listen", "models"):
        assert command in out


@pytest.mark.parametrize(("command", "task"), [("run", 11), ("say", 5), ("listen", 3)])
def test_should_exit_2_with_not_built_message_when_command_is_a_stub(
    command: str, task: int, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command]) == 2
    assert capsys.readouterr().err.strip() == f"jarvis {command}: not built yet (M1 task {task})"


def test_should_print_every_model_without_network_when_dry_run(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network() -> object:
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr(models, "_open_client", no_network)
    assert main(["models", "fetch", "--dry-run"]) == 0
    out = capsys.readouterr().out
    for spec in models.REGISTRY.values():
        assert spec.name in out
        assert spec.url in out
        assert str(models.model_path(spec)) in out


def test_should_limit_dry_run_to_named_models(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "fetch", "--dry-run", "whisper-tiny.en"]) == 0
    out = capsys.readouterr().out
    assert "whisper-tiny.en" in out
    assert "whisper-base.en" not in out


def test_should_exit_2_when_fetching_an_unknown_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["models", "fetch", "--dry-run", "nope"]) == 2
    assert "whisper-base.en" in capsys.readouterr().err


def test_should_show_size_only_for_cached_models_when_listing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = models.REGISTRY["whisper-tiny.en"]
    target = models.model_path(spec)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * 2048)
    assert main(["models", "list"]) == 0
    lines = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert set(lines) == set(models.REGISTRY)
    assert "2.0 KB" in lines["whisper-tiny.en"]
    assert "KB" not in lines["whisper-base.en"]
