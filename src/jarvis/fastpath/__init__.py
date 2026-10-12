"""Fast path: certain-only local command matching and execution (FRS 5.4)."""

from jarvis.fastpath.executor import FastPathDeclined, execute
from jarvis.fastpath.intents import Intent
from jarvis.fastpath.matcher import match

__all__ = ["FastPathDeclined", "Intent", "execute", "match"]
