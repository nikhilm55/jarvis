"""The web research failure, kept apart so the brain can import it without the runner."""

__all__ = ["ResearchError"]


class ResearchError(Exception):
    """The research run failed; `code` is a FinalResponse error code (TIMEOUT, NETWORK …)."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the error code and the message the brain can explain."""
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
