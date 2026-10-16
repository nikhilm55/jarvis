"""Consent: what Jarvis may touch, and the broker that asks before it touches it (FRS 5.11)."""

from jarvis.consent.scope import Access, Scope, ScopeError, parse_scopes, source_of

__all__ = ["Access", "Scope", "ScopeError", "parse_scopes", "source_of"]
