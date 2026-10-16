"""Tests for the deny/allow lists (FR-SAFE-09) and the ToolSpec additions."""

from pathlib import Path

import pytest

from jarvis.config import PolicySettings
from jarvis.policy import Tier, ToolSpec
from jarvis.policy.lists import denied, path_scopes
from jarvis.policy.model import max_tier


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("secrets", "Documents", "Documents/ok", "work"):
        (tmp_path / name).mkdir()
    return tmp_path


def deny(paths: list[str] | None = None, commands: list[str] | None = None) -> PolicySettings:
    return PolicySettings(deny_paths=paths or ["~/secrets"], deny_commands=commands or [])


@pytest.mark.parametrize(
    "args",
    [
        {"path": "~/secrets/key"},
        {"path": "~/secrets"},
        {"src": "~/work/a", "dst": "$HOME/secrets/b"},
        {"paths": ["~/work/a", "~/secrets/b"]},
        {"path": "secrets/key"},
        {"path": "~/work/../secrets/key"},
        {"cmd": "cat ~/secrets/key"},
        {"command": "cp x ~/secrets/y"},
        {"cmd": "echo hi>~/secrets/f"},
        {"cmd": "ls | wc -l < ~/secrets/f"},
        {"cmd": "tool --out=~/secrets/f"},
        {"cmd": "cat '~/secrets/key'"},
        {"cmd": "cat ~/sec*"},
        {"cmd": "cat ~/secrets/'unterminated"},
    ],
)
def test_should_deny_when_an_argument_resolves_under_a_deny_path(
    home: Path, args: dict[str, object]
) -> None:
    assert denied(args, deny()) is not None


def test_should_deny_when_a_symlink_points_into_a_denied_path(home: Path) -> None:
    (home / "innocent").symlink_to(home / "secrets")
    assert denied({"path": "~/innocent/key"}, deny()) is not None
    assert denied({"cmd": "cat innocent/key"}, deny()) is not None


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"path": "~/work/a"},
        {"path": "~/secrets-old/a"},
        {"cmd": "ls ~/work"},
        {"text": "~/secrets/key"},
        {"cmd": 7},
    ],
)
def test_should_not_deny_when_no_argument_is_under_a_deny_path(
    home: Path, args: dict[str, object]
) -> None:
    assert denied(args, deny()) is None


def test_should_deny_a_command_that_matches_a_deny_command_regex() -> None:
    settings = deny(commands=[r"^git\s+push", r"\bnpm publish\b"])
    assert denied({"cmd": "git push origin main"}, settings) is not None
    assert denied({"command": "cd x && npm publish"}, settings) is not None
    assert denied({"cmd": "git status"}, settings) is None
    assert denied({"path": "git push"}, settings) is None


def test_should_deny_nothing_when_the_lists_are_empty() -> None:
    assert denied({"cmd": "rm -rf ~", "path": "~/secrets"}, PolicySettings()) is None


def test_should_map_a_path_argument_to_the_consent_scope_of_its_folder(home: Path) -> None:
    settings = PolicySettings()
    assert path_scopes({"path": "~/Documents/a"}, "read", settings) == ("files.documents:read",)
    assert path_scopes({"src": "~/Documents/a", "dst": "Documents/b"}, "write", settings) == (
        "files.documents:write",
    )
    assert path_scopes({"path": "~/work/a"}, "read", settings) == ()
    assert (
        path_scopes({"text": "~/Documents/a", "cmd": "cat ~/Documents/a"}, "read", settings) == ()
    )


def test_should_exempt_an_allow_listed_path_from_the_scope_mapping(home: Path) -> None:
    settings = PolicySettings(allow_paths=["~/Documents/ok"])
    assert path_scopes({"path": "~/Documents/ok/a"}, "write", settings) == ()
    assert path_scopes({"path": "~/Documents/other"}, "write", settings) == (
        "files.documents:write",
    )


def test_should_not_let_the_allow_list_lift_a_deny() -> None:
    settings = PolicySettings(deny_paths=["~/secrets"], allow_paths=["~/secrets"])
    assert denied({"path": "~/secrets/a"}, settings) is not None


def test_should_pick_the_riskier_tier() -> None:
    assert max_tier(Tier.T1, Tier.T3) == Tier.T3
    assert max_tier(Tier.T3, Tier.T0) == Tier.T3
    assert max_tier(Tier.T2, Tier.T2) == Tier.T2


def test_should_reject_a_classifier_that_is_not_callable() -> None:
    with pytest.raises(ValueError, match="classify"):
        ToolSpec("x.tool", Tier.T1, classify="nope")  # type: ignore[arg-type]
    assert ToolSpec("x.tool", Tier.T1, undoable=True).undoable is True
