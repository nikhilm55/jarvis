"""The allowlisted environment of the brain's claude child (R45)."""

from collections.abc import Mapping

__all__ = ["brain_env"]

_ALLOWED = frozenset(
    {
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
        "https_proxy",
        "no_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "NODE_EXTRA_CA_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
)

_ALLOWED_PREFIXES = ("LC_", "XDG_")

_DENIED_PREFIXES = ("ANTHROPIC_", "CLAUDE", "MCP_", "OTEL_")


def brain_env(environ: Mapping[str, str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the explicit environment for the headless claude child."""
    result: dict[str, str] = {}
    for name, value in environ.items():
        if name.startswith(_DENIED_PREFIXES):
            continue
        if name in _ALLOWED or name.startswith(_ALLOWED_PREFIXES):
            result[name] = value
    if extra is not None:
        result.update(extra)
    return result
