"""The tool registry: the one table of tools the gate knows."""

from jarvis.policy.model import ToolSpec

_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    """Add a tool spec to the registry."""
    existing = _REGISTRY.get(spec.name)
    if existing is not None:
        if existing == spec:
            return
        raise ValueError(f"conflicting registration for {spec.name!r}")
    _REGISTRY[spec.name] = spec


def get(name: str) -> ToolSpec | None:
    """Look up a registered tool spec."""
    return _REGISTRY.get(name)
