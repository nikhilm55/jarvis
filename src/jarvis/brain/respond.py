"""The respond contract for one turn (R24, FR-IO-01): validate, one repair, then a fallback."""

from collections.abc import Callable

from jarvis.brain.failures import ToolError, contract_fallback
from jarvis.contract import ContractError, FinalResponse, repair_message, validate_response
from jarvis.log import get_logger


class RespondGate:
    """Accepts a turn's `jarvis.respond` payload and resolves the turn through `finish`."""

    def __init__(self, turn_id: str, finish: Callable[[FinalResponse], None]) -> None:
        """Bind the gate to a turn id and the callback that resolves the turn."""
        self._turn_id = turn_id
        self._finish = finish
        self._repair_used = False
        self._final: FinalResponse | None = None
        self._log = get_logger("brain")

    @property
    def final(self) -> FinalResponse | None:
        """The response that resolved the turn, if any."""
        return self._final

    @property
    def repair_used(self) -> bool:
        """Whether the one allowed repair has been spent."""
        return self._repair_used

    def force(self, response: FinalResponse) -> None:
        """Resolve the turn with `response` unless it is already resolved."""
        if self._final is None:
            self._final = response
            self._finish(response)

    def submit(self, args: dict[str, object]) -> str:
        """Validate a respond payload; raise ToolError with the repair text the first time."""
        if self._final is not None:
            raise ToolError("respond was already accepted; the turn is over")
        try:
            response = validate_response(args)
        except ContractError as err:
            self._log.warning(
                "contract violation",
                extra={
                    "turn_id": self._turn_id,
                    "problems": err.problems,
                    "repair_used": self._repair_used,
                },
            )
            if not self._repair_used:
                self._repair_used = True
                raise ToolError(repair_message(err)) from err
            self.force(contract_fallback())
            return "The response could not be accepted, so the turn has ended."
        self.force(response)
        return "ok"
