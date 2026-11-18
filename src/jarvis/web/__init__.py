"""The web tool (web.research) and its gate policy: T0, no consent question.

Looking something up on the web is what the user asked for when they ask a question that
needs it, so it runs without a confirmation in every mode. It reads no personal data and
changes nothing on the PC: the research runs in a sealed session with only WebSearch and
WebFetch (see `jarvis.web.researcher`). What comes back is data; any later action built
from it still meets R83 provenance, so a web page cannot make Jarvis act without the user.
"""

from jarvis.policy import Tier, ToolSpec, register

WEB_TOOLS = (ToolSpec("web.research", Tier.T0),)

for _spec in WEB_TOOLS:
    register(_spec)

__all__ = ["WEB_TOOLS"]
