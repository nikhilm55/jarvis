"""Tests for jarvis.brain.env.brain_env."""

import pytest

from jarvis.brain.env import brain_env

ALLOWLISTED_NAMES = [
    "HOME",
    "USER",
    "LOGNAME",
    "PATH",
    "SHELL",
    "LANG",
    "LANGUAGE",
    "TZ",
    "TMPDIR",
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "no_proxy",
    "NO_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "LC_ALL",
    "LC_CTYPE",
    "XDG_RUNTIME_DIR",
    "XDG_CONFIG_HOME",
]

DROPPED_NAMES = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CONFIG_DIR",
    "CLAUDECODE",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ID",
    "MCP_TIMEOUT",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "DISPLAY",
    "PYTHONPATH",
    "VIRTUAL_ENV",
]


@pytest.mark.parametrize("name", ALLOWLISTED_NAMES)
def test_should_keep_allowlisted_name_when_present(name: str) -> None:
    environ = {name: "value"}
    result = brain_env(environ)
    assert result == {name: "value"}


@pytest.mark.parametrize("name", DROPPED_NAMES)
def test_should_drop_disallowed_name_when_present(name: str) -> None:
    environ = {name: "value"}
    result = brain_env(environ)
    assert result == {}


def test_should_return_only_kept_names_when_mixed_environment() -> None:
    environ = {
        "HOME": "/home/user",
        "ANTHROPIC_API_KEY": "not-for-the-child",  # pragma: allowlist secret
        "CLAUDE_CONFIG_DIR": "/config",
        "MCP_TIMEOUT": "30",
        "PATH": "/usr/bin",
        "GITHUB_TOKEN": "token",
    }
    result = brain_env(environ)
    assert result == {"HOME": "/home/user", "PATH": "/usr/bin"}


def test_should_add_extra_names_when_given() -> None:
    environ = {"HOME": "/home/user"}
    extra = {"JARVIS_MCP_TOKEN": "token", "FAKE_CLAUDE_LOG": "log"}
    result = brain_env(environ, extra)
    assert result == {
        "HOME": "/home/user",
        "JARVIS_MCP_TOKEN": "token",
        "FAKE_CLAUDE_LOG": "log",
    }


def test_should_override_inherited_value_when_extra_provides_same_name() -> None:
    environ = {"PATH": "/usr/bin"}
    extra = {"PATH": "/custom/bin"}
    result = brain_env(environ, extra)
    assert result == {"PATH": "/custom/bin"}


def test_should_not_modify_input_mapping_when_called() -> None:
    environ = {
        "HOME": "/home/user",
        "ANTHROPIC_API_KEY": "not-for-the-child",  # pragma: allowlist secret
    }
    original = dict(environ)
    brain_env(environ)
    assert environ == original


def test_should_return_different_dict_object_when_called() -> None:
    environ = {"HOME": "/home/user"}
    result = brain_env(environ)
    assert result is not environ


def test_should_return_empty_dict_when_environment_is_empty() -> None:
    result = brain_env({})
    assert result == {}


def test_should_return_only_extra_when_environment_is_empty_and_extra_given() -> None:
    extra = {"JARVIS_MCP_TOKEN": "token"}
    result = brain_env({}, extra)
    assert result == {"JARVIS_MCP_TOKEN": "token"}


WINDOWS_NAMES = [
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "USERNAME",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "TEMP",
    "TMP",
]


@pytest.mark.parametrize("name", WINDOWS_NAMES)
def test_should_drop_windows_name_when_platform_is_linux(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "linux")
    assert brain_env({name: "value"}) == {}


def test_should_give_the_old_linux_result_when_windows_names_are_mixed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "linux")
    environ = {name: "value" for name in WINDOWS_NAMES} | {"HOME": "/h", "PATH": "/bin"}
    assert brain_env(environ) == {"HOME": "/h", "PATH": "/bin"}


@pytest.mark.parametrize("name", WINDOWS_NAMES)
def test_should_keep_windows_name_when_platform_is_win32(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "win32")
    assert brain_env({name: "value"}) == {name: "value"}


@pytest.mark.parametrize("name", ["SystemRoot", "ComSpec", "LocalAppData", "Temp"])
def test_should_keep_mixed_case_windows_name_when_platform_is_win32(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "win32")
    assert brain_env({name: "value"}) == {name: "value"}


@pytest.mark.parametrize("name", ["SystemRoot", "SYSTEMROOT"])
def test_should_drop_mixed_case_windows_name_when_platform_is_linux(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "linux")
    assert brain_env({name: "value"}) == {}


@pytest.mark.parametrize(
    "name",
    [
        "ANTHROPIC_API_KEY",
        "Anthropic_Api_Key",
        "CLAUDECODE",
        "MCP_TIMEOUT",
        "OTEL_X",
        "AWS_SECRET_ACCESS_KEY",
    ],
)
def test_should_still_drop_denied_and_unlisted_names_when_platform_is_win32(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.brain.env.sys.platform", "win32")
    result = brain_env({name: "value", "SYSTEMROOT": "C:\\Windows"})
    assert result == {"SYSTEMROOT": "C:\\Windows"}
